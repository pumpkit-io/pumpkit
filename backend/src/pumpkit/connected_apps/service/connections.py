"""Users' connections to apps: their Connected apps. Flushes, never commits."""

from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.connected_apps.models import AppConnection, OAuthRefreshToken


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
