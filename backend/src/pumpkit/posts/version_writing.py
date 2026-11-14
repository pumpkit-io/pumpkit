"""
The steps of writing a Version, shared by posts' mediator (a Post's first Version) and
scheduling's (Feedback, which it gates). Flush-only: the mediators commit around the model calls.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.auth.service.users as users_service
import pumpkit.billing.service as billing_service
import pumpkit.x_connection.service as x_connections_service
from pumpkit.auth.models import User
from pumpkit.billing.allowance import Draw
from pumpkit.core.errors import ConflictError, NotFoundError, RetryLaterError
from pumpkit.core.logging import logger
from pumpkit.core.text import drop_unstorable
from pumpkit.core.time import as_utc
from pumpkit.posts import media as media_service
from pumpkit.posts import service
from pumpkit.posts.formats import Format
from pumpkit.posts.models import ATTEMPT_SUCCEEDED, Post, VersionAttempt
from pumpkit.posts.plans import Plan
from pumpkit.posts.schemas import (
    FailedFeedbackResponse,
    PartResponse,
    PlanResponse,
    StartingTextResponse,
    TextPartResponse,
    TextResponse,
    VersionResponse,
)
from pumpkit.posts.writing.post_writing import revision_inputs
from pumpkit.posts.writing.prompts.post import PostInputs
from pumpkit.posts.writing.starting_text import StartingText, starting_text
from pumpkit.posts.writing.versions import EarlierVersion
from pumpkit.posts.writing_state import is_writing
from pumpkit.x_connection.x_length import x_post_max_chars, x_weighted_length

# Starting a Post and giving Feedback share one budget per User, failed attempts included,
# so one account can't run up an unbounded model bill.
VERSION_ATTEMPTS_PER_WINDOW = 30
VERSION_ATTEMPT_WINDOW = timedelta(hours=1)


def next_attempt_at(attempted_at: list[datetime], count: int = 1) -> Optional[datetime]:
    """
    When the User may make their next `count` attempts, given when they made those in the last
    window, or None if they may now. The window rolls: each attempt stops counting a window after it.
    """
    if len(attempted_at) + count <= VERSION_ATTEMPTS_PER_WINDOW:
        return None
    # The attempts that must stop counting first; concurrent requests can store a surplus too.
    surplus = len(attempted_at) + count - 1 - VERSION_ATTEMPTS_PER_WINDOW
    return sorted(attempted_at)[surplus] + VERSION_ATTEMPT_WINDOW


async def check_attempt_limit(
    db: AsyncSession, *, user_id: str, now: datetime, count: int = 1
) -> None:
    """
    Room for `count` more attempts in the window. Writes still in flight count from when they
    started, lost ones included.
    """
    since = now - VERSION_ATTEMPT_WINDOW
    attempted_at = await service.attempt_times_since(db, user_id=user_id, since=since)
    attempted_at += await service.writes_started_since(db, user_id=user_id, since=since)
    retry_at = next_attempt_at(attempted_at, count)
    if retry_at is None:
        return
    if len(attempted_at) >= VERSION_ATTEMPTS_PER_WINDOW:
        detail = (
            f"You've made {VERSION_ATTEMPTS_PER_WINDOW} attempts at a version in the last hour."
        )
    else:
        left = VERSION_ATTEMPTS_PER_WINDOW - len(attempted_at)
        detail = (
            f"Writing {count} posts needs {count} attempts at a version, and you have {left} "
            f"left of the {VERSION_ATTEMPTS_PER_WINDOW} an hour allows."
        )
    raise RetryLaterError(detail, retry_at=retry_at, now=now)


async def _generation_draw(db: AsyncSession, *, user_id: str, now: datetime) -> Optional[Draw]:
    """One Generation of the User's Allowance at `now`; None when it has no cap on them."""
    allowance = await billing_service.get_allowance(db, user_id=user_id, moment=now, now=now)
    if allowance is None or allowance.limits.generations is None:
        return None
    used = await service.count_versions_between(
        db, user_id=user_id, start=allowance.period.start, end=allowance.period.end
    )
    return Draw(allowance=allowance, count="generations", used=used, needed=1, moment=now)


async def check_generation_left(
    db: AsyncSession, *, user_id: str, now: datetime, count: int = 1
) -> None:
    """
    Room for `count` more Generations in the User's Allowance or, once it is used up, their
    Top-ups, checked before the model calls. Writes in flight hold one each. A Version recorded
    after concurrent requests filled both is kept, over the limit.
    """
    draw = await _generation_draw(db, user_id=user_id, now=now)
    if draw is not None:
        in_flight = await service.count_writes_in_flight(db, user_id=user_id, now=now)
        await billing_service.check_room_with_top_ups(
            db, user_id=user_id, draw=replace(draw, used=draw.used + in_flight, needed=count)
        )


async def generations_left(db: AsyncSession, *, user_id: str, now: datetime) -> Optional[int]:
    """The most `count` `check_generation_left` allows now; None when the User has no cap."""
    draw = await _generation_draw(db, user_id=user_id, now=now)
    if draw is None:
        return None
    in_flight = await service.count_writes_in_flight(db, user_id=user_id, now=now)
    return await billing_service.left_with_top_ups(
        db, user_id=user_id, draw=replace(draw, used=draw.used + in_flight)
    )


async def charge_generation(
    db: AsyncSession, *, user_id: str, version: VersionAttempt, now: datetime
) -> None:
    """Charge a just-recorded Version to a Top-up when the Allowance had no Generation left."""
    # Concurrent Versions then count each other before charging.
    await users_service.lock_user_id(db, user_id=user_id)
    draw = await _generation_draw(db, user_id=user_id, now=now)
    if draw is None:
        return
    await billing_service.charge_shortfall(
        db,
        user_id=user_id,
        # The count includes `version` itself.
        draw=replace(draw, used=draw.used - 1),
        version_attempt_id=version.id,
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
        error=drop_unstorable(f"{type(error).__name__}: {error}"),
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


def plan_response(plan: Optional[Plan]) -> Optional[PlanResponse]:
    """The Plan as a response shows it, without the planner's reasoning."""
    if plan is None:
        return None
    return PlanResponse(
        core_idea=plan.core_idea,
        takeaway=plan.takeaway,
        funnel=plan.funnel,
        desired_action=plan.desired_action,
        format=plan.format,
        length=plan.length,
        structure=plan.structure,
    )


def version_response(attempt: VersionAttempt, char_limit: int) -> VersionResponse:
    assert attempt.version_number is not None and attempt.parts is not None
    return VersionResponse(
        id=attempt.id,
        number=attempt.version_number,
        feedback=attempt.feedback,
        format=attempt.format,
        parts=_part_responses(attempt.parts, char_limit),
        first_reply=attempt.first_reply,
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
        first_reply=starting.first_reply,
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
        first_reply=attempt.starting_text_first_reply,
    )


def post_text(post: Post) -> Optional[StartingText]:
    """The Post's Text, or None while it has no Version."""
    if post.text_format is None or post.text_parts is None or post.text_version_number is None:
        return None
    return StartingText(
        format=post.text_format,
        parts=list(post.text_parts),
        version_number=post.text_version_number,
        first_reply=post.text_first_reply,
    )


def failed_feedback_response(post: Post, *, now: datetime) -> Optional[FailedFeedbackResponse]:
    """The Feedback whose write failed or timed out, until the User moves on; None while writing."""
    feedback, format = post.unwritten_feedback, post.unwritten_feedback_format
    if feedback is None or format is None or is_writing(post, now=now):
        return None
    return FailedFeedbackResponse(feedback=feedback, format=format)


def text_response(post: Post, char_limit: int) -> Optional[TextResponse]:
    """The Post's Text, or None while it has no Version."""
    text = post_text(post)
    if text is None:
        return None
    media = media_service.text_media_by_part(post)
    return TextResponse(
        format=text.format,
        parts=[
            TextPartResponse(
                **part.model_dump(), media=[media_service.media_response(m) for m in on_part]
            )
            for part, on_part in zip(_part_responses(text.parts, char_limit), media, strict=True)
        ],
        first_reply=text.first_reply,
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


async def post_still_writing(
    db: AsyncSession, *, user_id: str, post_id: str, started_at: datetime, now: datetime
) -> Optional[Post]:
    """
    The Post, locked, for the write that started at `started_at` to record its outcome. None, and
    the write records nothing, when the Post was deleted or moved on: the write outlived the
    timeout, so the User was told it failed, or a Retry or another Feedback started another write.
    """
    post = await service.get_user_post(db, user_id=user_id, post_id=post_id, for_update=True)
    if post is None:
        logger.info("Write of post %s recorded nothing: the post was deleted", post_id)
        return None
    if (
        post.writing_since is None
        or as_utc(post.writing_since) != started_at
        or not is_writing(post, now=now)
    ):
        logger.info(
            "Write of post %s started at %s recorded nothing: the post moved on",
            post_id,
            started_at.isoformat(),
        )
        return None
    return post


def versions_of(post: Post) -> list[VersionAttempt]:
    return [attempt for attempt in post.attempts if attempt.status == ATTEMPT_SUCCEEDED]


@dataclass(frozen=True)
class NextVersion:
    """What writing the Version after a Post's latest needs, read before the model calls."""

    # The Brief, the Positioning it was planned with and its Plan, in the Feedback's Format.
    inputs: PostInputs
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
    feedback: str,
    format: Optional[Format],
    sent_text: Optional[list[str]],
    now: datetime,
) -> NextVersion:
    """
    For Feedback on `post`'s Text, in `format` or else the Text's, from its Plan and the
    Positioning its Brief was planned with. Holds the Text until the Version is recorded. Raises
    when the Post has no Text yet or was written before Plans, when another Version is being
    written, when `sent_text` isn't the saved Text, or when the User is over the attempt limit or
    has no Generation left.
    """
    versions = versions_of(post)
    text = post_text(post)
    if not versions or text is None:
        if is_writing(post, now=now):
            raise ConflictError(
                "Pumpkit is still writing this post's first version. Give feedback once it's written."
            )
        raise ConflictError("This post has no version to give feedback on. Start a new post.")
    char_limit = await char_limit_for(db, user_id=user.id)
    inputs = revision_inputs(
        brief=post.brief,
        positioning=post.idea.brief.positioning,
        plan=post.idea.plan,
        format=format or text.format,
        previous=text.format,
        char_limit=char_limit,
    )
    if inputs is None:
        raise ConflictError(
            "This post was written before plans existed, so it can't take feedback. "
            "Edit the text by hand, or start a new post."
        )
    service.check_not_writing(post, now=now)
    if sent_text is not None and sent_text != text.parts:
        raise ConflictError("Your last edit to the text isn't saved yet. Save it, then try again.")
    await check_attempt_limit(db, user_id=user.id, now=now)
    await check_generation_left(db, user_id=user.id, now=now)
    latest = versions[-1]
    service.start_writing(post, now=now, feedback=feedback, format=format or text.format)
    return NextVersion(
        inputs=inputs,
        earlier=[
            EarlierVersion(
                number=v.version_number or 0,
                feedback=v.feedback,
                format=v.format,
                parts=v.parts or [],
                starting_text=stored_starting_text(v),
                first_reply=v.first_reply,
            )
            for v in versions
        ],
        starting_text=starting_text(text, latest.format, latest.parts or [], latest.first_reply),
        format=format or text.format,
        sequence=len(post.attempts) + 1,
        number=len(versions) + 1,
        char_limit=char_limit,
    )
