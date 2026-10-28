"""
The steps of writing a Version, shared by posts' mediator (a Post's first Version) and
scheduling's (Feedback, which it gates). Flush-only: the mediators commit around the model calls.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.x_connection.service as x_connections_service
from pumpkit.auth.models import User
from pumpkit.core.errors import ConflictError, NotFoundError, RetryLaterError
from pumpkit.posts import service
from pumpkit.posts.formats import Format
from pumpkit.posts.models import ATTEMPT_SUCCEEDED, Post, VersionAttempt
from pumpkit.posts.schemas import PartResponse, TellResponse, VersionResponse
from pumpkit.posts.writing.corpus import Corpus
from pumpkit.posts.writing.versions import EarlierVersion
from pumpkit.x_connection.x_length import x_post_max_chars, x_weighted_length

# Starting a Post and giving Feedback share one budget per User, failed attempts included,
# so one account can't run up an unbounded model bill.
VERSION_ATTEMPTS_PER_WINDOW = 30
VERSION_ATTEMPT_WINDOW = timedelta(hours=1)


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


async def check_attempt_limit(db: AsyncSession, *, user_id: str, now: datetime) -> None:
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


async def record_failed_attempt(
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


async def char_limit_for(db: AsyncSession, *, user_id: str) -> int:
    """
    The post limit of the User's X account, X's default when none is connected. A Version's text
    over it is flagged, not refused, and the limit shown follows the account as it is now.
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


async def user_post(db: AsyncSession, *, user: User, post_id: str) -> Post:
    post = await service.get_user_post(db, user_id=user.id, post_id=post_id)
    if post is None:
        raise NotFoundError("Post not found.")
    return post


def versions_of(post: Post) -> list[VersionAttempt]:
    return [attempt for attempt in post.attempts if attempt.status == ATTEMPT_SUCCEEDED]


@dataclass(frozen=True)
class NextVersion:
    """What writing the Version after a Post's latest needs, read before the model calls."""

    corpus: Corpus
    earlier: list[EarlierVersion]
    format: Format
    sequence: int
    number: int
    char_limit: int


async def prepare_next_version(
    db: AsyncSession, *, user: User, post: Post, format: Optional[Format], now: datetime
) -> NextVersion:
    """
    For Feedback on `post`, in `format` or else the latest Version's, with the corpus the Post
    started with. Raises when the Post has no Version yet or the User is over the attempt limit.
    """
    versions = versions_of(post)
    if not versions:
        raise ConflictError("This Post has no Version to give Feedback on. Start a new Post.")
    await check_attempt_limit(db, user_id=user.id, now=now)
    return NextVersion(
        corpus=await service.corpus_for_post(db, post=post),
        earlier=[
            EarlierVersion(feedback=v.feedback, format=v.format, final_parts=v.final_parts or [])
            for v in versions
        ],
        format=format or versions[-1].format,
        sequence=len(post.attempts) + 1,
        number=len(versions) + 1,
        char_limit=await char_limit_for(db, user_id=user.id),
    )
