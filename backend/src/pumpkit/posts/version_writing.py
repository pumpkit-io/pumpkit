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
from pumpkit.core.time import as_utc
from pumpkit.posts import service
from pumpkit.posts.formats import Format
from pumpkit.posts.models import ATTEMPT_SUCCEEDED, Post, VersionAttempt
from pumpkit.posts.schemas import (
    PartResponse,
    StartingTextResponse,
    TextResponse,
    VersionResponse,
)
from pumpkit.posts.writing.corpus import Corpus
from pumpkit.posts.writing.starting_text import StartingText, starting_text
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


def _part_responses(parts: list[str], char_limit: int) -> list[PartResponse]:
    return [
        PartResponse(text=text, char_count=x_weighted_length(text), char_limit=char_limit)
        for text in parts
    ]


def version_response(attempt: VersionAttempt, char_limit: int) -> VersionResponse:
    assert attempt.version_number is not None and attempt.parts is not None
    return VersionResponse(
        id=attempt.id,
        number=attempt.version_number,
        feedback=attempt.feedback,
        format=attempt.format,
        parts=_part_responses(attempt.parts, char_limit),
        starting_text=_starting_text_response(attempt, char_limit),
        created_at=as_utc(attempt.created_at),
    )


def _starting_text_response(
    attempt: VersionAttempt, char_limit: int
) -> Optional[StartingTextResponse]:
    starting = stored_starting_text(attempt)
    if starting is None:
        return None
    return StartingTextResponse(
        format=starting.format,
        parts=_part_responses(starting.parts, char_limit),
        version_number=starting.version_number,
    )


def stored_starting_text(attempt: VersionAttempt) -> Optional[StartingText]:
    if (
        attempt.starting_text_format is None
        or attempt.starting_text_parts is None
        or attempt.starting_text_version_number is None
    ):
        return None
    return StartingText(
        format=attempt.starting_text_format,
        parts=list(attempt.starting_text_parts),
        version_number=attempt.starting_text_version_number,
    )


def post_text(post: Post) -> Optional[StartingText]:
    """The Post's Text, or None while it has no Version."""
    if post.text_format is None or post.text_parts is None or post.text_version_number is None:
        return None
    return StartingText(
        format=post.text_format,
        parts=list(post.text_parts),
        version_number=post.text_version_number,
    )


def text_response(post: Post, char_limit: int) -> Optional[TextResponse]:
    """The Post's Text, or None while it has no Version."""
    text = post_text(post)
    if text is None:
        return None
    return TextResponse(
        format=text.format,
        parts=_part_responses(text.parts, char_limit),
        version_number=text.version_number,
        edited=post.text_edited,
    )


async def user_post(
    db: AsyncSession, *, user: User, post_id: str, for_update: bool = False
) -> Post:
    post = await service.get_user_post(db, user_id=user.id, post_id=post_id, for_update=for_update)
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
    # The Post's Text, when it isn't the latest Version as written.
    starting_text: Optional[StartingText]
    format: Format
    sequence: int
    number: int
    char_limit: int


async def prepare_next_version(
    db: AsyncSession,
    *,
    user: User,
    post: Post,
    format: Optional[Format],
    sent_text: Optional[list[str]],
    now: datetime,
) -> NextVersion:
    """
    For Feedback on `post`'s Text, in `format` or else the Text's, with the corpus the Post
    started with, and holds the Text until the Version is recorded. Raises when the Post has no
    Text yet, when another Version is being written, when `sent_text` isn't the saved Text, or
    when the User is over the attempt limit.
    """
    versions = versions_of(post)
    text = post_text(post)
    if not versions or text is None:
        raise ConflictError("This Post has no Version to give Feedback on. Start a new Post.")
    service.check_not_writing(post, now=now)
    if sent_text is not None and sent_text != text.parts:
        raise ConflictError("Your last edit to the Text isn't saved yet. Save it, then try again.")
    await check_attempt_limit(db, user_id=user.id, now=now)
    latest = versions[-1]
    service.start_writing(post, now=now)
    return NextVersion(
        corpus=await service.corpus_for_post(db, post=post),
        earlier=[
            EarlierVersion(
                number=v.version_number or 0,
                feedback=v.feedback,
                format=v.format,
                parts=v.parts or [],
                starting_text=stored_starting_text(v),
            )
            for v in versions
        ],
        starting_text=starting_text(text, latest.format, latest.parts or []),
        format=format or text.format,
        sequence=len(post.attempts) + 1,
        number=len(versions) + 1,
        char_limit=await char_limit_for(db, user_id=user.id),
    )
