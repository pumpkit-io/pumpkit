from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.x_connection.service as x_connections_service
from pumpkit.auth.models import User
from pumpkit.core.errors import ConflictError, NotFoundError, RefusedError, RetryLaterError
from pumpkit.core.time import as_utc
from pumpkit.posts import service
from pumpkit.posts.formats import Format
from pumpkit.posts.llm import LLM
from pumpkit.posts.models import ATTEMPT_SUCCEEDED, Post, VersionAttempt
from pumpkit.posts.schemas import (
    PartResponse,
    PostResponse,
    PostsPageResponse,
    PostSummaryResponse,
    TellResponse,
    VersionResponse,
)
from pumpkit.posts.writing.versions import EarlierVersion, write_first_version, write_next_version
from pumpkit.x_connection.x_length import x_post_max_chars, x_weighted_length

# Starting a Post and giving Feedback share one budget per User, failed attempts included,
# so one account can't run up an unbounded model bill.
VERSION_ATTEMPTS_PER_WINDOW = 30
VERSION_ATTEMPT_WINDOW = timedelta(hours=1)

# Where the User adds Inspiration authors.
HOME_PAGE = "/home"


def next_attempt_at(attempted_at: list[datetime]) -> Optional[datetime]:
    """
    When the User may make their next attempt, given when they made those in the last window,
    or None if they may now. The window rolls: each attempt stops counting a window after it.
    """
    if len(attempted_at) < VERSION_ATTEMPTS_PER_WINDOW:
        return None
    # Concurrent requests can store more than the limit, so skip past the surplus too.
    surplus = len(attempted_at) - VERSION_ATTEMPTS_PER_WINDOW
    return sorted(attempted_at)[surplus] + VERSION_ATTEMPT_WINDOW


async def _check_attempt_limit(db: AsyncSession, *, user_id: str, now: datetime) -> None:
    attempted_at = await service.attempt_times_since(
        db, user_id=user_id, since=now - VERSION_ATTEMPT_WINDOW
    )
    retry_at = next_attempt_at(attempted_at)
    if retry_at is not None:
        raise RetryLaterError(
            f"You've made {VERSION_ATTEMPTS_PER_WINDOW} attempts at a Version in the last hour.",
            retry_at=retry_at,
            now=now,
        )


async def _keep_failed_attempt(
    db: AsyncSession,
    *,
    post: Post,
    sequence: int,
    feedback: Optional[str],
    format: Format,
    error: Exception,
    now: datetime,
) -> None:
    await service.record_failed_attempt(
        db,
        post=post,
        sequence=sequence,
        feedback=feedback,
        format=format,
        error=f"{type(error).__name__}: {error}",
        now=now,
    )
    # Commit before the caller re-raises, or the request session rolls the failed attempt back.
    await db.commit()


async def _char_limit(db: AsyncSession, *, user_id: str) -> int:
    """
    The post limit of the User's X account, X's default when none is connected. A Final over it
    is flagged, not refused, and the limit shown follows the account as it is now.
    """
    connection = await x_connections_service.get_connection(db, user_id=user_id)
    return x_post_max_chars(connection.subscription_type if connection else None)


def version_response(attempt: VersionAttempt, char_limit: int) -> VersionResponse:
    assert attempt.version_number is not None and attempt.final_parts is not None
    assert attempt.slop_tells is not None
    format = attempt.format
    return VersionResponse(
        id=attempt.id,
        number=attempt.version_number,
        feedback=attempt.feedback,
        format=format,
        parts=[
            PartResponse(
                text=text,
                char_count=x_weighted_length(text),
                char_limit=char_limit,
            )
            for text in attempt.final_parts
        ],
        tells=[TellResponse(**tell) for tell in attempt.slop_tells],
    )


async def _user_post(db: AsyncSession, *, user: User, post_id: str) -> Post:
    post = await service.get_user_post(db, user_id=user.id, post_id=post_id)
    if post is None:
        raise NotFoundError("Post not found.")
    return post


def _versions(post: Post) -> list[VersionAttempt]:
    return [attempt for attempt in post.attempts if attempt.status == ATTEMPT_SUCCEEDED]


async def list_posts(db: AsyncSession, user: User, limit: int, offset: int) -> PostsPageResponse:
    """A page of the User's Posts, newest first."""
    # One past the page tells whether another page follows.
    posts = await service.list_user_posts(db, user_id=user.id, limit=limit + 1, offset=offset)
    return PostsPageResponse(
        data=[
            PostSummaryResponse(
                id=post.id,
                brief=post.brief,
                created_at=as_utc(post.created_at),
                version_count=len(_versions(post)),
            )
            for post in posts[:limit]
        ],
        next_offset=offset + limit if len(posts) > limit else None,
    )


async def get_post(db: AsyncSession, user: User, post_id: str) -> PostResponse:
    """The User's Post with every Version, in order."""
    post = await _user_post(db, user=user, post_id=post_id)
    char_limit = await _char_limit(db, user_id=user.id)
    versions = [version_response(v, char_limit) for v in _versions(post)]
    return PostResponse(id=post.id, brief=post.brief, versions=versions)


async def start_post(
    db: AsyncSession, llm: LLM, user: User, brief: str, format: Format, now: datetime
) -> PostResponse:
    """
    Start a Post from the Brief and write its first Version in `format`.

    The Post and its attempt are stored only after the calls, so no transaction stays open
    across them; a failure is stored as a failed attempt before the error is re-raised.
    """
    user_id = user.id
    corpus = await service.corpus_for_user(db, user_id=user_id)
    if not corpus.post_ids:
        raise RefusedError(
            "Add an Inspiration author with posts before writing a Post.", fix_page=HOME_PAGE
        )
    await _check_attempt_limit(db, user_id=user_id, now=now)
    char_limit = await _char_limit(db, user_id=user_id)
    # Ends the read transaction before the calls, which can take minutes.
    await db.commit()

    try:
        written = await write_first_version(llm, corpus, brief, format, char_limit)
    except Exception as error:
        post = await service.create_post(db, user_id=user_id, brief=brief, corpus=corpus, now=now)
        await _keep_failed_attempt(
            db, post=post, sequence=1, feedback=None, format=format, error=error, now=now
        )
        raise

    post = await service.create_post(db, user_id=user_id, brief=brief, corpus=corpus, now=now)
    version = await service.record_version(
        db, post=post, sequence=1, version_number=1, feedback=None, written=written, now=now
    )
    await db.commit()
    return PostResponse(
        id=post.id, brief=post.brief, versions=[version_response(version, char_limit)]
    )


async def add_version(
    db: AsyncSession,
    llm: LLM,
    user: User,
    post_id: str,
    feedback: str,
    format: Optional[Format],
    now: datetime,
) -> VersionResponse:
    """
    Write the next Version of the User's Post from Feedback, in `format` or else the latest
    Version's, with the corpus the Post started with. Stored after the calls like `start_post`,
    and a failure likewise.
    """
    post = await _user_post(db, user=user, post_id=post_id)
    versions = _versions(post)
    if not versions:
        raise ConflictError("This Post has no Version to give Feedback on. Start a new Post.")
    await _check_attempt_limit(db, user_id=user.id, now=now)
    corpus = await service.corpus_for_post(db, post=post)
    earlier = [
        EarlierVersion(feedback=v.feedback, format=v.format, final_parts=v.final_parts or [])
        for v in versions
    ]
    format = format or versions[-1].format
    sequence = len(post.attempts) + 1
    char_limit = await _char_limit(db, user_id=user.id)
    # Ends the read transaction before the calls, which can take minutes.
    await db.commit()

    try:
        written = await write_next_version(
            llm, corpus, post.brief, earlier, feedback, format, char_limit
        )
    except Exception as error:
        await _keep_failed_attempt(
            db,
            post=post,
            sequence=sequence,
            feedback=feedback,
            format=format,
            error=error,
            now=now,
        )
        raise

    version = await service.record_version(
        db,
        post=post,
        sequence=sequence,
        version_number=len(versions) + 1,
        feedback=feedback,
        written=written,
        now=now,
    )
    await db.commit()
    return version_response(version, char_limit)
