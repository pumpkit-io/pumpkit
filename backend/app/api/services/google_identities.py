from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GoogleIdentity


async def get_google_identity(
    db: AsyncSession,
    subject: str,
) -> Optional[GoogleIdentity]:
    """Get a Google identity by its Google subject."""
    query = select(GoogleIdentity).where(GoogleIdentity.subject == subject)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_google_identity(
    db: AsyncSession,
    google_identity: GoogleIdentity,
) -> None:
    """Create a new Google identity in the database."""
    db.add(google_identity)
    await db.commit()
