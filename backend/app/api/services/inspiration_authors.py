from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datetimes import as_utc
from app.db.models import AuthorFetch, AuthorPost, InspirationAuthor


@dataclass(frozen=True)
class AuthorSummary:
    handle: str
    last_fetched_at: Optional[datetime]
    post_count: int


async def list_authors(db: AsyncSession, *, user_id: str) -> list[AuthorSummary]:
    """The User's Inspiration authors in list order, each with its shared fetch state."""
    post_counts = (
        select(AuthorPost.handle, func.count().label("post_count"))
        .group_by(AuthorPost.handle)
        .subquery()
    )
    result = await db.execute(
        select(
            InspirationAuthor.handle,
            AuthorFetch.last_fetched_at,
            func.coalesce(post_counts.c.post_count, 0),
        )
        .outerjoin(AuthorFetch, AuthorFetch.handle == InspirationAuthor.handle)
        .outerjoin(post_counts, post_counts.c.handle == InspirationAuthor.handle)
        .where(InspirationAuthor.user_id == user_id)
        .order_by(InspirationAuthor.position)
    )
    return [
        AuthorSummary(
            handle=handle,
            last_fetched_at=None if last_fetched_at is None else as_utc(last_fetched_at),
            post_count=post_count,
        )
        for handle, last_fetched_at, post_count in result.all()
    ]


async def get_author(db: AsyncSession, *, user_id: str, handle: str) -> Optional[InspirationAuthor]:
    result = await db.execute(
        select(InspirationAuthor).where(
            InspirationAuthor.user_id == user_id, InspirationAuthor.handle == handle
        )
    )
    return result.scalar_one_or_none()


async def count_authors(db: AsyncSession, *, user_id: str) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(InspirationAuthor)
        .where(InspirationAuthor.user_id == user_id)
    )
    return result.scalar_one()


async def add_author(
    db: AsyncSession, *, user_id: str, handle: str, now: datetime
) -> InspirationAuthor:
    """Put `handle` at the end of the User's list. Flushes."""
    last_position = (
        await db.execute(
            select(func.max(InspirationAuthor.position)).where(InspirationAuthor.user_id == user_id)
        )
    ).scalar_one()
    author = InspirationAuthor(
        user_id=user_id,
        handle=handle,
        position=0 if last_position is None else last_position + 1,
        added_at=now,
    )
    db.add(author)
    await db.flush()
    return author


async def remove_author(db: AsyncSession, author: InspirationAuthor) -> None:
    """Take the author off its User's list; its fetched posts stay. Flushes."""
    await db.delete(author)
    await db.flush()
