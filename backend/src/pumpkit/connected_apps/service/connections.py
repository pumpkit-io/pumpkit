"""Users' connections to apps: their Connected apps. Flushes, never commits."""

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.connected_apps.models import AppConnection


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
