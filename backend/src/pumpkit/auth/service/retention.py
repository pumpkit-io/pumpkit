"""
Deletes Session and Magic link records, with their IP addresses and user agents, once
they are past the retention period the Privacy Policy states. Flushes, never commits.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import MagicLink, RefreshToken

# How long after expiry a refresh token or Magic link is kept. The Privacy Policy states it.
RETENTION_AFTER_EXPIRY = timedelta(days=90)


async def purge_expired(db: AsyncSession, *, now: datetime) -> None:
    """
    Run opportunistically on Magic link requests and Session starts, like expired pending
    X authorizations, so no separate process or timer is needed.
    """
    cutoff = now - RETENTION_AFTER_EXPIRY
    await db.execute(delete(RefreshToken).where(RefreshToken.expires_at < cutoff))
    await db.execute(delete(MagicLink).where(MagicLink.expires_at < cutoff))
    await db.flush()
