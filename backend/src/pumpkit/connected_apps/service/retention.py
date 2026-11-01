"""Deletes what apps leave behind once it is stale. Flushes, never commits."""

from datetime import datetime, timedelta

from sqlalchemy import delete, exists
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.connected_apps.models import AppConnection, OAuthAuthorization, OAuthClient

UNUSED_CLIENT_AGE = timedelta(days=30)


async def purge_expired(db: AsyncSession, *, now: datetime) -> None:
    """
    Run opportunistically from registration, as `auth.service.retention` runs on sign-in.
    Hosted apps register a client per connection, so unused ones pile up.
    """
    cutoff = now - UNUSED_CLIENT_AGE
    await db.execute(
        delete(OAuthClient).where(
            OAuthClient.kind == "registered",
            OAuthClient.created_at < cutoff,
            ~exists().where(AppConnection.client_id == OAuthClient.id),
            ~exists().where(
                OAuthAuthorization.client_id == OAuthClient.id,
                OAuthAuthorization.created_at >= cutoff,
            ),
        )
    )
