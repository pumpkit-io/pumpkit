from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ThirdPartyAuth, ThirdPartyAuthProvider


async def get_third_party_auth(
    db: AsyncSession,
    provider: ThirdPartyAuthProvider,
    subject: str,
) -> Optional[ThirdPartyAuth]:
    """Get a third-party auth record by provider and subject."""
    query = select(ThirdPartyAuth).where(
        ThirdPartyAuth.provider == provider,
        ThirdPartyAuth.subject == subject,
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_third_party_auth(
    db: AsyncSession,
    third_party_auth: ThirdPartyAuth,
) -> None:
    """Create a new third-party auth record in the database."""
    db.add(third_party_auth)
    await db.commit()
