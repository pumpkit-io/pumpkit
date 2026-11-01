"""Users' connections to apps: their Connected apps. Flushes, never commits."""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.connected_apps.models import AppConnection, OAuthRefreshToken
from pumpkit.core.time import as_utc

# How fresh `last_used_at` stays: a minute, so an app calling tools doesn't write its row every call.
_LAST_USED_RESOLUTION = timedelta(minutes=1)


async def find_or_create(
    db: AsyncSession, *, user_id: str, client_id: str, scope: str, resource: str, now: datetime
) -> AppConnection:
    """The User's unrevoked connection to the app, so connecting it again keeps one row."""
    connection = await _find_unrevoked(db, user_id=user_id, client_id=client_id)
    if connection is not None:
        return connection
    connection = AppConnection(
        user_id=user_id, client_id=client_id, scope=scope, resource=resource, created_at=now
    )
    try:
        # A savepoint, so losing the race to the unique index leaves the transaction usable.
        async with db.begin_nested():
            db.add(connection)
    except IntegrityError:
        winner = await _find_unrevoked(db, user_id=user_id, client_id=client_id)
        if winner is None:
            raise
        return winner
    return connection


async def _find_unrevoked(
    db: AsyncSession, *, user_id: str, client_id: str
) -> Optional[AppConnection]:
    return (
        await db.execute(
            select(AppConnection).where(
                AppConnection.user_id == user_id,
                AppConnection.client_id == client_id,
                AppConnection.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def record_use(db: AsyncSession, connection: AppConnection, *, now: datetime) -> None:
    """Set `last_used_at` to `now`, unless it was set less than a minute before."""
    stale_before = now - _LAST_USED_RESOLUTION
    last_used_at = connection.last_used_at
    if last_used_at is not None and as_utc(last_used_at) > stale_before:
        return
    # Conditional, so concurrent calls write the row once a minute between them.
    await db.execute(
        update(AppConnection)
        .where(
            AppConnection.id == connection.id,
            or_(AppConnection.last_used_at.is_(None), AppConnection.last_used_at <= stale_before),
        )
        .values(last_used_at=now)
        .execution_options(synchronize_session="fetch")
    )


async def revoke(db: AsyncSession, connection_id: str, *, now: datetime) -> None:
    """Disconnect the app: every token check refuses a revoked connection."""
    await db.execute(
        update(AppConnection)
        .where(AppConnection.id == connection_id, AppConnection.revoked_at.is_(None))
        .values(revoked_at=now)
        .execution_options(synchronize_session="fetch")
    )
    # Marked too, so an audit of the tokens alone shows which ones died with the connection.
    await db.execute(
        update(OAuthRefreshToken)
        .where(
            OAuthRefreshToken.app_connection_id == connection_id,
            OAuthRefreshToken.rotated_at.is_(None),
            OAuthRefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
