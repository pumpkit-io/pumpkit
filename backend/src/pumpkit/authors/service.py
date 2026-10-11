from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.authors.models import AuthorFetch, AuthorPost, InspirationAuthor
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.core.time import as_utc


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


async def store_new_posts(
    db: AsyncSession, *, handle: str, posts: Sequence[FetchedPost], now: datetime
) -> int:
    """
    Store the posts not already stored, under `handle`; return how many were new. Flushes.

    Select-then-insert rather than ON CONFLICT so it runs on SQLite too, which leaves two
    concurrent fetches of one handle able to collide on the primary key.
    """
    unique = {post.post_id: post for post in posts}
    if not unique:
        return 0
    existing = set(
        (await db.execute(select(AuthorPost.id).where(AuthorPost.id.in_(unique)))).scalars()
    )
    new = [post for post_id, post in unique.items() if post_id not in existing]
    db.add_all(
        AuthorPost(
            id=post.post_id,
            handle=handle,
            text=post.text,
            posted_at=post.posted_at,
            fetched_at=now,
        )
        for post in new
    )
    await db.flush()
    return len(new)


async def count_posts(db: AsyncSession, *, handle: str) -> int:
    result = await db.execute(
        select(func.count()).select_from(AuthorPost).where(AuthorPost.handle == handle)
    )
    return result.scalar_one()


async def last_fetched_at(db: AsyncSession, *, handle: str) -> Optional[datetime]:
    """When any User last fetched `handle`, or None if it never was."""
    fetch = await db.get(AuthorFetch, handle)
    return None if fetch is None else as_utc(fetch.last_fetched_at)


async def record_fetch(db: AsyncSession, *, handle: str, now: datetime) -> None:
    """Set when `handle` was last fetched. Flushes."""
    fetch = await db.get(AuthorFetch, handle)
    if fetch is None:
        db.add(AuthorFetch(handle=handle, last_fetched_at=now))
    else:
        fetch.last_fetched_at = now
    await db.flush()
