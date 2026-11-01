"""Access and refresh tokens an app holds for its connection. Flushes, never commits."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.connected_apps.models import AppConnection, OAuthAccessToken, OAuthRefreshToken
from pumpkit.core.security import generate_token, hash_token

# The one scope every app gets (ADR 0020): an app may use every tool the User can.
SCOPE = "pumpkit"

ACCESS_TOKEN_LIFETIME = timedelta(hours=1)
REFRESH_TOKEN_LIFETIME = timedelta(days=90)
# A refresh token rotated this recently may be presented again, for a retry after a lost response.
REFRESH_REUSE_GRACE = timedelta(minutes=2)
CODE_LIFETIME = timedelta(minutes=2)
AUTHORIZATION_REQUEST_LIFETIME = timedelta(minutes=30)

ACCESS_TOKEN_PREFIX = "pumpkit_at_"
REFRESH_TOKEN_PREFIX = "pumpkit_rt_"


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    refresh_token_id: str


async def issue_pair(db: AsyncSession, *, app_connection_id: str, now: datetime) -> IssuedTokens:
    access_token = ACCESS_TOKEN_PREFIX + generate_token(32)
    refresh_token = REFRESH_TOKEN_PREFIX + generate_token(32)
    refresh_row = OAuthRefreshToken(
        app_connection_id=app_connection_id,
        token_hash=hash_token(refresh_token),
        created_at=now,
        expires_at=now + REFRESH_TOKEN_LIFETIME,
    )
    db.add_all(
        [
            OAuthAccessToken(
                app_connection_id=app_connection_id,
                token_hash=hash_token(access_token),
                created_at=now,
                expires_at=now + ACCESS_TOKEN_LIFETIME,
            ),
            refresh_row,
        ]
    )
    await db.flush()
    return IssuedTokens(
        access_token=access_token, refresh_token=refresh_token, refresh_token_id=refresh_row.id
    )


async def find_refresh_token(
    db: AsyncSession, token: str
) -> Optional[tuple[OAuthRefreshToken, AppConnection]]:
    row = (
        await db.execute(
            select(OAuthRefreshToken, AppConnection)
            .join(AppConnection, AppConnection.id == OAuthRefreshToken.app_connection_id)
            .where(OAuthRefreshToken.token_hash == hash_token(token))
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1])


async def rotate(db: AsyncSession, presented: OAuthRefreshToken, *, now: datetime) -> IssuedTokens:
    """
    A new pair in the same connection. A token rotated again within the grace keeps its first
    rotation, and two concurrent rotations both get a pair, as a retry within the grace would.
    """
    issued = await issue_pair(db, app_connection_id=presented.app_connection_id, now=now)
    if presented.rotated_at is None:
        presented.rotated_at = now
        presented.replaced_by = issued.refresh_token_id
    return issued


async def find_access_token(
    db: AsyncSession, token: str
) -> Optional[tuple[OAuthAccessToken, AppConnection]]:
    row = (
        await db.execute(
            select(OAuthAccessToken, AppConnection)
            .join(AppConnection, AppConnection.id == OAuthAccessToken.app_connection_id)
            .where(OAuthAccessToken.token_hash == hash_token(token))
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1])
