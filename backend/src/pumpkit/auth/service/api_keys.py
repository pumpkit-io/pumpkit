"""
Storage of API keys (ADR 0012). Keys never reach the Sessions module and never mint
access tokens. Flushes, never commits.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import ApiKey
from pumpkit.core.security import generate_token, hash_token

# Fixed, so a leaked key is easy to grep for in logs and repos.
SECRET_PREFIX = "pumpkit_"
# The secret prefix plus 8 random characters: enough to tell keys apart, far too few to guess one.
_DISPLAY_PREFIX_LENGTH = len(SECRET_PREFIX) + 8


async def create_api_key(
    db: AsyncSession, *, user_id: str, name: str, now: datetime
) -> tuple[ApiKey, str]:
    """Store a new key for the User and return it with its secret, which nothing stores."""
    secret = SECRET_PREFIX + generate_token(32)
    api_key = ApiKey(
        user_id=user_id,
        name=name,
        key_hash=hash_token(secret),
        prefix=secret[:_DISPLAY_PREFIX_LENGTH],
        created_at=now,
    )
    db.add(api_key)
    await db.flush()
    return api_key, secret


async def list_unrevoked_api_keys(db: AsyncSession, *, user_id: str) -> list[ApiKey]:
    """The User's unrevoked keys, oldest first."""
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))
        .order_by(ApiKey.created_at, ApiKey.id)
    )
    return list(result.scalars())
