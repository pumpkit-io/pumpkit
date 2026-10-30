from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.authors import service
from pumpkit.authors.handles import normalize_handle
from pumpkit.authors.models import InspirationAuthor
from pumpkit.authors.schemas import (
    InspirationAuthorResponse,
    InspirationAuthorsListResponse,
)
from pumpkit.authors.x_reader import HandleNotFoundError, RecentPosts, XReader
from pumpkit.core.errors import ConflictError, NotFoundError, RefusedError, RetryLaterError

MAX_INSPIRATION_AUTHORS = 3
REFRESH_COOLDOWN = timedelta(hours=1)


def next_refresh_at(last_fetched_at: Optional[datetime], *, now: datetime) -> Optional[datetime]:
    """When a handle last fetched at `last_fetched_at` may be refreshed, or None if it may now."""
    if last_fetched_at is None:
        return None
    allowed_at = last_fetched_at + REFRESH_COOLDOWN
    return allowed_at if now < allowed_at else None


async def _listed_author(db: AsyncSession, *, user_id: str, handle: str) -> InspirationAuthor:
    """The User's Inspiration author for `handle` as typed in a URL, or a 404."""
    not_listed = NotFoundError("That handle isn't one of your inspiration authors.")
    try:
        handle = normalize_handle(handle)
    except ValueError:
        raise not_listed
    author = await service.get_author(db, user_id=user_id, handle=handle)
    if author is None:
        raise not_listed
    return author


def _response(summary: service.AuthorSummary) -> InspirationAuthorResponse:
    return InspirationAuthorResponse(
        handle=summary.handle,
        last_fetched_at=summary.last_fetched_at,
        post_count=summary.post_count,
        photo_url=summary.photo_url,
    )


async def list_authors(db: AsyncSession, user: User) -> InspirationAuthorsListResponse:
    summaries = await service.list_authors(db, user_id=user.id)
    return InspirationAuthorsListResponse(data=[_response(summary) for summary in summaries])


def _already_listed(handle: str) -> ConflictError:
    return ConflictError(f"@{handle} is already one of your inspiration authors.")


async def add_author(
    db: AsyncSession, reader: XReader, user: User, handle: str, now: datetime
) -> InspirationAuthorResponse:
    """
    Fetch `handle`'s recent posts, store the new ones and add the handle to the User's list.

    The list checks run first so a duplicate or a fourth author costs no twitterapi.io call,
    and a handle fetched less than an hour ago is added from its stored posts without one.
    A 404 for a handle X doesn't know and a 422 for one without original posts store nothing.
    """
    user_id = user.id
    if await service.get_author(db, user_id=user_id, handle=handle):
        raise _already_listed(handle)
    if await service.count_authors(db, user_id=user_id) >= MAX_INSPIRATION_AUTHORS:
        raise ConflictError(
            f"You can have up to {MAX_INSPIRATION_AUTHORS} Inspiration authors. "
            "Remove one to add another."
        )

    last_fetched_at = await service.last_fetched_at(db, handle=handle)
    if next_refresh_at(last_fetched_at, now=now) is None:
        recent = await _fetch(reader, handle)
        has_posts = bool(recent.posts)
        if has_posts:
            await service.store_new_posts(db, handle=handle, posts=recent.posts, now=now)
            await service.record_fetch(db, handle=handle, now=now, photo_url=recent.photo_url)
    else:
        has_posts = await service.count_posts(db, handle=handle) > 0
    if not has_posts:
        raise RefusedError(f"@{handle} has no original posts to learn from.")

    try:
        await service.add_author(db, user_id=user_id, handle=handle, now=now)
        await db.commit()
    except IntegrityError:
        # A concurrent add of the same handle won the unique (user_id, handle) constraint.
        raise _already_listed(handle)

    return await _author_response(db, user_id=user_id, handle=handle)


async def refresh_author(
    db: AsyncSession, reader: XReader, user: User, handle: str, now: datetime
) -> InspirationAuthorResponse:
    """
    Fetch the latest posts of one of the User's Inspiration authors and store the new ones.

    Fetched posts are shared across Users, so the hour between fetches is per handle.
    """
    user_id = user.id
    handle = (await _listed_author(db, user_id=user_id, handle=handle)).handle

    retry_at = next_refresh_at(await service.last_fetched_at(db, handle=handle), now=now)
    if retry_at is not None:
        raise RetryLaterError(
            f"@{handle} was fetched less than an hour ago.", retry_at=retry_at, now=now
        )

    recent = await _fetch(reader, handle)
    await service.store_new_posts(db, handle=handle, posts=recent.posts, now=now)
    await service.record_fetch(db, handle=handle, now=now, photo_url=recent.photo_url)
    await db.commit()
    return await _author_response(db, user_id=user_id, handle=handle)


async def _fetch(reader: XReader, handle: str) -> RecentPosts:
    try:
        return await reader.fetch_recent_posts(handle)
    except HandleNotFoundError:
        raise NotFoundError(f"@{handle} doesn't exist on X.")


async def remove_author(db: AsyncSession, user: User, handle: str) -> None:
    """Take `handle` off the User's list; its fetched posts stay for other Users."""
    author = await _listed_author(db, user_id=user.id, handle=handle)
    await service.remove_author(db, author)
    await db.commit()


async def _author_response(
    db: AsyncSession, *, user_id: str, handle: str
) -> InspirationAuthorResponse:
    summaries = await service.list_authors(db, user_id=user_id)
    return _response(next(summary for summary in summaries if summary.handle == handle))
