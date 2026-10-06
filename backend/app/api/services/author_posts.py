from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datetimes import as_utc
from app.core.x_reader import FetchedPost
from app.db.models import AuthorFetch, AuthorPost


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
