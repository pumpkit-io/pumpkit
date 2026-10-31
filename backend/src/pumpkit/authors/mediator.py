import math
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.authors import service
from pumpkit.authors.handles import normalize_handle
from pumpkit.authors.models import (
    LOOKUP_FOUND,
    MISS_MISSING,
    MISS_PRIVATE,
    MISS_SUSPENDED,
    InspirationAuthor,
)
from pumpkit.authors.schemas import (
    AuthorDirectoryEntryResponse,
    AuthorDirectoryResponse,
    InspirationAuthorResponse,
    InspirationAuthorsListResponse,
)
from pumpkit.authors.x_reader import (
    FetchedProfile,
    HandleNotFoundError,
    HandleSuspendedError,
    RecentPosts,
    XReader,
)
from pumpkit.core.config import settings
from pumpkit.core.errors import (
    ConflictError,
    NotFoundError,
    RefusalError,
    RefusedError,
    RetryLaterError,
)

MAX_INSPIRATION_AUTHORS = 3
REFRESH_COOLDOWN = timedelta(hours=1)
LOOKUP_HOUR = timedelta(hours=1)
LOOKUP_DAY = timedelta(days=1)


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
        name=summary.name,
        photo_url=summary.photo_url,
    )


async def list_authors(db: AsyncSession, user: User) -> InspirationAuthorsListResponse:
    summaries = await service.list_authors(db, user_id=user.id)
    return InspirationAuthorsListResponse(data=[_response(summary) for summary in summaries])


async def list_directory(db: AsyncSession) -> AuthorDirectoryResponse:
    entries = await service.list_directory(db)
    return AuthorDirectoryResponse(
        data=[
            AuthorDirectoryEntryResponse(
                handle=entry.handle,
                name=entry.name,
                photo_url=entry.photo_url,
                persona_count=entry.persona_count,
            )
            for entry in entries
        ]
    )


def _already_listed(handle: str) -> ConflictError:
    return ConflictError(f"@{handle} is already one of your inspiration authors.")


async def add_author(
    db: AsyncSession, reader: XReader, user: User, handle: str, now: datetime
) -> InspirationAuthorResponse:
    """
    Add `handle` to the User's list, picked from the Author directory or looked up on X (ADR 0019).

    The list checks run first so a duplicate or a fourth author costs no twitterapi.io call. A
    handle not in the directory is looked up first, and posts any User fetched within
    `AUTHOR_POSTS_REUSE_DAYS` are reused without a fetch.
    """
    user_id = user.id
    if await service.get_author(db, user_id=user_id, handle=handle):
        raise _already_listed(handle)
    if await service.count_authors(db, user_id=user_id) >= MAX_INSPIRATION_AUTHORS:
        raise ConflictError(
            f"You can have up to {MAX_INSPIRATION_AUTHORS} Inspiration authors. "
            "Remove one to add another."
        )
    if not await service.in_directory(db, handle=handle):
        await _look_up(db, reader, user_id=user_id, handle=handle, now=now)

    last_fetched_at = await service.last_fetched_at(db, handle=handle)
    reuse_window = timedelta(days=settings.AUTHOR_POSTS_REUSE_DAYS)
    if last_fetched_at is None or now >= last_fetched_at + reuse_window:
        recent = await _fetch(reader, handle)
        has_posts = bool(recent.posts)
        if has_posts:
            await service.store_new_posts(db, handle=handle, posts=recent.posts, now=now)
            await _record_fetch(db, handle=handle, recent=recent, now=now)
    else:
        has_posts = await service.count_posts(db, handle=handle) > 0
    if not has_posts:
        raise RefusedError(f"@{handle} has no posts of its own to learn from")

    try:
        await service.add_author(db, user_id=user_id, handle=handle, now=now)
        await db.commit()
    except IntegrityError:
        # A concurrent add of the same handle won the unique (user_id, handle) constraint.
        raise _already_listed(handle)

    return await _author_response(db, user_id=user_id, handle=handle)


def _isnt_on_x(handle: str) -> RefusalError:
    return NotFoundError(f"@{handle} isn't on X")


def _miss_error(handle: str, reason: str) -> RefusalError:
    if reason == MISS_PRIVATE:
        return RefusedError(f"@{handle} is private, so Pumpkit can't read its posts")
    return _isnt_on_x(handle)


async def _look_up(
    db: AsyncSession, reader: XReader, *, user_id: str, handle: str, now: datetime
) -> None:
    """
    Add `handle` to the Author directory from its profile on X, or raise why it can't be added.
    A remembered miss answers without a lookup and isn't counted towards the lookup limits.
    """
    reason = await service.remembered_miss(db, handle=handle, now=now)
    if reason is not None:
        raise _miss_error(handle, reason)
    await _check_lookup_limits(db, user_id=user_id, now=now)

    profile: Optional[FetchedProfile] = None
    try:
        profile = await reader.look_up_profile(handle)
        reason = MISS_PRIVATE if profile.protected else None
    except HandleSuspendedError:
        reason = MISS_SUSPENDED
    except HandleNotFoundError:
        reason = MISS_MISSING
    await service.log_lookup(
        db, user_id=user_id, handle=handle, now=now, result=reason or LOOKUP_FOUND
    )
    if reason is not None:
        miss_days = (
            settings.AUTHOR_PRIVATE_MISS_DAYS
            if reason == MISS_PRIVATE
            else settings.AUTHOR_MISS_DAYS
        )
        await service.remember_miss(
            db, handle=handle, reason=reason, remembered_until=now + timedelta(days=miss_days)
        )
    elif profile is not None:
        await service.add_directory_entry(
            db, handle=handle, name=profile.name, photo_url=profile.photo_url, now=now
        )
    # Early commit: the lookup was paid for, so its answer outlives a failed posts fetch.
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent lookup of the same handle stored its answer first.
        await db.rollback()
    if reason is not None:
        raise _miss_error(handle, reason)


async def _check_lookup_limits(db: AsyncSession, *, user_id: str, now: datetime) -> None:
    """Refuse a lookup over the User's hourly or daily limit, or over the Instance's daily cap."""
    user_limits = [
        (settings.AUTHOR_LOOKUP_HOURLY_LIMIT, LOOKUP_HOUR),
        (settings.AUTHOR_LOOKUP_DAILY_LIMIT, LOOKUP_DAY),
    ]
    waits = []
    for limit, window in user_limits:
        counted = await service.count_lookups(db, since=now - window, user_id=user_id)
        wait = _limited_until(counted, limit=limit, window=window, now=now)
        if wait is not None:
            waits.append(wait)
    if waits:
        retry_at = max(waits)
        minutes = max(1, math.ceil((retry_at - now).total_seconds() / 60))
        unit = "minute" if minutes == 1 else "minutes"
        raise RetryLaterError(
            f"You've looked up a lot of handles. Try again in {minutes} {unit}.",
            retry_at=retry_at,
            now=now,
        )

    counted = await service.count_lookups(db, since=now - LOOKUP_DAY)
    retry_at = _limited_until(
        counted, limit=settings.AUTHOR_LOOKUP_INSTANCE_DAILY_LIMIT, window=LOOKUP_DAY, now=now
    )
    if retry_at is not None:
        raise RetryLaterError(
            "Looking up new handles is paused for today. "
            "Pick from the suggestions or try again tomorrow.",
            retry_at=retry_at,
            now=now,
        )


def _limited_until(
    counted: service.LookupCount, *, limit: int, window: timedelta, now: datetime
) -> Optional[datetime]:
    """When the oldest of `counted` leaves `window` and frees a lookup, or None if one is free."""
    if counted.count < limit:
        return None
    return (counted.oldest or now) + window


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
    await _record_fetch(db, handle=handle, recent=recent, now=now)
    await db.commit()
    return await _author_response(db, user_id=user_id, handle=handle)


async def _fetch(reader: XReader, handle: str) -> RecentPosts:
    try:
        return await reader.fetch_recent_posts(handle)
    except HandleNotFoundError:
        raise _isnt_on_x(handle)


async def _record_fetch(
    db: AsyncSession, *, handle: str, recent: RecentPosts, now: datetime
) -> None:
    await service.record_fetch(
        db, handle=handle, now=now, name=recent.name, photo_url=recent.photo_url
    )


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
