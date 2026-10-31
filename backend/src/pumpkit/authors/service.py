from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.authors.models import (
    SOURCE_LOOKUP,
    SOURCE_SEED,
    AuthorDirectoryEntry,
    AuthorFetch,
    AuthorHandleMiss,
    AuthorLookup,
    AuthorPost,
    InspirationAuthor,
)
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.core.time import as_utc


@dataclass(frozen=True)
class AuthorSummary:
    handle: str
    last_fetched_at: Optional[datetime]
    post_count: int
    name: Optional[str]
    photo_url: Optional[str]


@dataclass(frozen=True)
class DirectoryEntrySummary:
    handle: str
    name: Optional[str]
    photo_url: Optional[str]
    persona_count: int


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
            AuthorDirectoryEntry.name,
            AuthorDirectoryEntry.photo_url,
        )
        .outerjoin(AuthorFetch, AuthorFetch.handle == InspirationAuthor.handle)
        .outerjoin(post_counts, post_counts.c.handle == InspirationAuthor.handle)
        .outerjoin(AuthorDirectoryEntry, AuthorDirectoryEntry.handle == InspirationAuthor.handle)
        .where(InspirationAuthor.user_id == user_id)
        .order_by(InspirationAuthor.position)
    )
    return [
        AuthorSummary(
            handle=handle,
            last_fetched_at=None if last_fetched_at is None else as_utc(last_fetched_at),
            post_count=post_count,
            name=name,
            photo_url=photo_url,
        )
        for handle, last_fetched_at, post_count, name, photo_url in result.all()
    ]


async def list_directory(db: AsyncSession) -> list[DirectoryEntrySummary]:
    """Every Author directory entry by handle, with how many Users have it in their Persona."""
    persona_counts = (
        select(InspirationAuthor.handle, func.count().label("persona_count"))
        .group_by(InspirationAuthor.handle)
        .subquery()
    )
    result = await db.execute(
        select(
            AuthorDirectoryEntry.handle,
            AuthorDirectoryEntry.name,
            AuthorDirectoryEntry.photo_url,
            func.coalesce(persona_counts.c.persona_count, 0),
        )
        .outerjoin(persona_counts, persona_counts.c.handle == AuthorDirectoryEntry.handle)
        .order_by(AuthorDirectoryEntry.handle)
    )
    return [
        DirectoryEntrySummary(
            handle=handle, name=name, photo_url=photo_url, persona_count=persona_count
        )
        for handle, name, photo_url, persona_count in result.all()
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


async def record_fetch(
    db: AsyncSession,
    *,
    handle: str,
    now: datetime,
    name: Optional[str],
    photo_url: Optional[str],
) -> None:
    """
    Set when `handle` was last fetched, and its directory entry's name and photo from what the
    fetch found, adding the entry if it has none. What the fetch didn't find stays, and so does
    a seeded entry's name, which was curated. Flushes.
    """
    fetch = await db.get(AuthorFetch, handle)
    if fetch is None:
        db.add(AuthorFetch(handle=handle, last_fetched_at=now))
    else:
        fetch.last_fetched_at = now
    entry = await db.get(AuthorDirectoryEntry, handle)
    if entry is None:
        entry = AuthorDirectoryEntry(handle=handle, added_at=now, source=SOURCE_LOOKUP)
        db.add(entry)
    if name is not None and entry.source != SOURCE_SEED:
        entry.name = name
    if photo_url is not None:
        entry.photo_url = photo_url
    await db.flush()


async def in_directory(db: AsyncSession, *, handle: str) -> bool:
    return await db.get(AuthorDirectoryEntry, handle) is not None


async def add_directory_entry(
    db: AsyncSession,
    *,
    handle: str,
    name: Optional[str],
    photo_url: Optional[str],
    now: datetime,
) -> None:
    """Add `handle` to the Author directory as found by a lookup on X. Flushes."""
    db.add(
        AuthorDirectoryEntry(
            handle=handle, name=name, photo_url=photo_url, added_at=now, source=SOURCE_LOOKUP
        )
    )
    await db.flush()


async def remembered_miss(db: AsyncSession, *, handle: str, now: datetime) -> Optional[str]:
    """Why a lookup of `handle` found it unusable, while that is still remembered."""
    miss = await db.get(AuthorHandleMiss, handle)
    if miss is None or now >= as_utc(miss.remembered_until):
        return None
    return miss.reason


async def remember_miss(
    db: AsyncSession, *, handle: str, reason: str, remembered_until: datetime
) -> None:
    """Remember why `handle` is unusable until `remembered_until`, replacing an older miss. Flushes."""
    miss = await db.get(AuthorHandleMiss, handle)
    if miss is None:
        db.add(AuthorHandleMiss(handle=handle, reason=reason, remembered_until=remembered_until))
    else:
        miss.reason = reason
        miss.remembered_until = remembered_until
    await db.flush()


async def log_lookup(
    db: AsyncSession, *, user_id: str, handle: str, now: datetime, result: str
) -> None:
    """Record one profile lookup on twitterapi.io. Flushes."""
    db.add(AuthorLookup(user_id=user_id, handle=handle, looked_up_at=now, result=result))
    await db.flush()


@dataclass(frozen=True)
class LookupCount:
    count: int
    # When the oldest counted lookup was made; None when none was.
    oldest: Optional[datetime]


async def count_lookups(
    db: AsyncSession, *, since: datetime, user_id: Optional[str] = None
) -> LookupCount:
    """The lookups made after `since`, by one User or, without `user_id`, by the whole Instance."""
    query = select(func.count(), func.min(AuthorLookup.looked_up_at)).where(
        AuthorLookup.looked_up_at > since
    )
    if user_id is not None:
        query = query.where(AuthorLookup.user_id == user_id)
    count, oldest = (await db.execute(query)).one()
    return LookupCount(count=count, oldest=None if oldest is None else as_utc(oldest))
