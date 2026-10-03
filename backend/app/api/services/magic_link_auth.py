from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MagicLink


async def create_magic_link(
    db: AsyncSession,
    magic_link: MagicLink,
) -> None:
    """Create a new magic link in the database."""
    db.add(magic_link)
    await db.commit()


async def get_magic_link_by_token_hash(
    db: AsyncSession,
    token_hash: str,
) -> Optional[MagicLink]:
    """Get a magic link by its token hash."""
    query = select(MagicLink).where(MagicLink.token_hash == token_hash)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_latest_magic_link_by_email(
    db: AsyncSession,
    email: str,
) -> Optional[MagicLink]:
    """Get the most recently sent magic link for an email (any status)."""
    query = (
        select(MagicLink)
        .where(MagicLink.email == email)
        .order_by(MagicLink.sent_at.desc())
        .limit(1)
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def invalidate_magic_links_for_email(
    db: AsyncSession,
    email: str,
) -> None:
    """Mark any outstanding (unconsumed) magic links for an email as consumed."""
    await db.execute(
        update(MagicLink)
        .where(MagicLink.email == email, MagicLink.consumed_at.is_(None))
        .values(consumed_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def atomically_consume_magic_link(
    db: AsyncSession,
    token_hash: str,
) -> Optional[MagicLink]:
    """
    Atomically mark a magic link as consumed in a single statement.
    Returns None if the token was already consumed (race condition).
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(MagicLink)
        .where(
            MagicLink.token_hash == token_hash,
            MagicLink.consumed_at.is_(None),
        )
        .values(consumed_at=now)
        .returning(MagicLink)
    )
    consumed = result.scalar_one_or_none()
    if consumed is None:
        return None
    await db.commit()
    return consumed
