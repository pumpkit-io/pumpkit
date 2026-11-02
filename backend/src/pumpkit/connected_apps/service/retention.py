"""Deletes what apps leave behind once it is stale. Flushes, never commits."""

from datetime import datetime, timedelta

from sqlalchemy import and_, delete, exists, or_
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.connected_apps.models import (
    AppConnection,
    OAuthAccessToken,
    OAuthAuthorization,
    OAuthClient,
    OAuthRefreshToken,
)

UNUSED_CLIENT_AGE = timedelta(days=30)
AUTHORIZATION_AGE = timedelta(days=1)
EXPIRED_ACCESS_TOKEN_AGE = timedelta(days=1)
EXPIRED_REFRESH_TOKEN_AGE = timedelta(days=90)
REVOKED_CONNECTION_AGE = timedelta(days=90)


async def purge_expired(db: AsyncSession, *, now: datetime) -> None:
    """
    Run opportunistically from registration and authorize, as `auth.service.retention` runs
    on sign-in. Hosted apps register a client per connection, so unused ones pile up.
    """
    await db.execute(
        delete(OAuthAccessToken).where(OAuthAccessToken.expires_at < now - EXPIRED_ACCESS_TOKEN_AGE)
    )
    await db.execute(
        delete(OAuthRefreshToken).where(
            OAuthRefreshToken.expires_at < now - EXPIRED_REFRESH_TOKEN_AGE
        )
    )
    # Their tokens and authorizations go with them by cascade, and their clients may then go too.
    await db.execute(
        delete(AppConnection).where(AppConnection.revoked_at < now - REVOKED_CONNECTION_AGE)
    )
    await db.execute(
        delete(OAuthAuthorization).where(OAuthAuthorization.created_at < now - AUTHORIZATION_AGE)
    )
    cutoff = now - UNUSED_CLIENT_AGE
    await db.execute(
        delete(OAuthClient).where(
            or_(
                and_(OAuthClient.kind == "registered", OAuthClient.created_at < cutoff),
                # Any URL serving a valid document makes a row, so stale unused ones go too.
                and_(
                    OAuthClient.kind == "metadata_document",
                    OAuthClient.metadata_expires_at < cutoff,
                ),
            ),
            ~exists().where(AppConnection.client_id == OAuthClient.id),
            ~exists().where(
                OAuthAuthorization.client_id == OAuthClient.id,
                OAuthAuthorization.created_at >= cutoff,
            ),
        )
    )
