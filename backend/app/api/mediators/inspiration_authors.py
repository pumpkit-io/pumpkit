from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.author_posts as author_posts_service
import app.api.services.inspiration_authors as inspiration_authors_service
from app.core.retry_later import RetryLaterError
from app.core.x_handles import normalize_handle
from app.core.x_reader import FetchedPost, HandleNotFoundError, XReader
from app.db.models import User
from app.schemas.inspiration_authors import InspirationAuthorResponse

MAX_INSPIRATION_AUTHORS = 3
REFRESH_COOLDOWN = timedelta(hours=1)


def next_refresh_at(last_fetched_at: Optional[datetime], *, now: datetime) -> Optional[datetime]:
    """When a handle last fetched at `last_fetched_at` may be refreshed, or None if it may now."""
    if last_fetched_at is None:
        return None
    allowed_at = last_fetched_at + REFRESH_COOLDOWN
    return allowed_at if now < allowed_at else None


def _already_listed(handle: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"@{handle} is already one of your Inspiration authors.",
    )


async def add_author(
    db: AsyncSession, reader: XReader, user: User, handle: str, now: datetime
) -> InspirationAuthorResponse:
    """
    Fetch `handle`'s recent posts, store the new ones and add the handle to the User's list.

    The list checks run first so a duplicate or a fourth author costs no twitterapi.io call.
    A 404 for a handle X doesn't know and a 422 for one without original posts store nothing.
    """
    user_id = user.id
    if await inspiration_authors_service.get_author(db, user_id=user_id, handle=handle):
        raise _already_listed(handle)
    if await inspiration_authors_service.count_authors(db, user_id=user_id) >= (
        MAX_INSPIRATION_AUTHORS
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You can have up to {MAX_INSPIRATION_AUTHORS} Inspiration authors. "
            "Remove one to add another.",
        )

    posts = await _fetch(reader, handle)
    if not posts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"@{handle} has no original posts to learn from.",
        )

    await author_posts_service.store_new_posts(db, handle=handle, posts=posts, now=now)
    await author_posts_service.record_fetch(db, handle=handle, now=now)
    try:
        await inspiration_authors_service.add_author(db, user_id=user_id, handle=handle, now=now)
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
    not_listed = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="That handle isn't one of your Inspiration authors.",
    )
    try:
        handle = normalize_handle(handle)
    except ValueError:
        raise not_listed
    if await inspiration_authors_service.get_author(db, user_id=user_id, handle=handle) is None:
        raise not_listed

    retry_at = next_refresh_at(
        await author_posts_service.last_fetched_at(db, handle=handle), now=now
    )
    if retry_at is not None:
        raise RetryLaterError(
            f"@{handle} was fetched less than an hour ago.", retry_at=retry_at, now=now
        )

    posts = await _fetch(reader, handle)
    await author_posts_service.store_new_posts(db, handle=handle, posts=posts, now=now)
    await author_posts_service.record_fetch(db, handle=handle, now=now)
    await db.commit()
    return await _author_response(db, user_id=user_id, handle=handle)


async def _fetch(reader: XReader, handle: str) -> list[FetchedPost]:
    try:
        return await reader.fetch_recent_posts(handle)
    except HandleNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"@{handle} doesn't exist on X."
        )


async def _author_response(
    db: AsyncSession, *, user_id: str, handle: str
) -> InspirationAuthorResponse:
    summaries = await inspiration_authors_service.list_authors(db, user_id=user_id)
    author = next(summary for summary in summaries if summary.handle == handle)
    return InspirationAuthorResponse(
        handle=author.handle, last_fetched_at=author.last_fetched_at, post_count=author.post_count
    )
