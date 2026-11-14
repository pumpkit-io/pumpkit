from datetime import datetime
from typing import Optional

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pumpkit.billing.models import TopUpCharge
from pumpkit.core.errors import ConflictError
from pumpkit.core.time import as_utc
from pumpkit.posts import media
from pumpkit.posts.formats import FORMAT_POST, Format
from pumpkit.posts.models import (
    ATTEMPT_FAILED,
    ATTEMPT_SUCCEEDED,
    Brief,
    Idea,
    Post,
    VersionAttempt,
)
from pumpkit.posts.writing.planning import PlannedBrief
from pumpkit.posts.writing.starting_text import StartingText
from pumpkit.posts.writing.versions import WrittenVersion
from pumpkit.posts.writing_state import WRITING_TIMEOUT, is_writing


async def get_user_post(
    db: AsyncSession, *, user_id: str, post_id: str, for_update: bool = False
) -> Optional[Post]:
    """
    The User's Post with its attempts in order, or None when it isn't theirs. `for_update` locks
    the Post's row until the transaction ends, for a change to its Text.
    """
    query = (
        select(Post)
        .where(Post.id == post_id, Post.user_id == user_id)
        .options(selectinload(Post.attempts))
    )
    if for_update:
        # Read afresh: the session may hold the Post from before another request changed it.
        query = query.with_for_update(of=Post).execution_options(populate_existing=True)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def attempt_times_since(db: AsyncSession, *, user_id: str, since: datetime) -> list[datetime]:
    """When the User attempted a Version after `since`, failed attempts included."""
    rows = await db.execute(
        select(VersionAttempt.created_at)
        .join(Post, VersionAttempt.post_id == Post.id)
        .where(Post.user_id == user_id, VersionAttempt.created_at > since)
    )
    return [as_utc(created_at) for created_at in rows.scalars()]


async def writes_started_since(
    db: AsyncSession, *, user_id: str, since: datetime
) -> list[datetime]:
    """
    When the User's writes still unrecorded started after `since`: each becomes an attempt once
    it ends, and stops counting here then.
    """
    rows = await db.execute(
        select(Post.writing_since).where(Post.user_id == user_id, Post.writing_since > since)
    )
    return [as_utc(started) for started in rows.scalars() if started is not None]


async def count_writes_in_flight(db: AsyncSession, *, user_id: str, now: datetime) -> int:
    """The User's writes started within the timeout, each charged a Generation if it succeeds."""
    return len(await writes_started_since(db, user_id=user_id, since=now - WRITING_TIMEOUT))


async def count_versions_between(
    db: AsyncSession, *, user_id: str, start: datetime, end: datetime
) -> int:
    """
    The Generations of the User's Allowance used in `[start, end)`: succeeded attempts only, less
    those charged to a Top-up, refunded or disputed since or not.
    """
    result = await db.execute(
        select(func.count())
        .select_from(VersionAttempt)
        .join(Post, VersionAttempt.post_id == Post.id)
        .where(
            Post.user_id == user_id,
            VersionAttempt.status == ATTEMPT_SUCCEEDED,
            VersionAttempt.created_at >= start,
            VersionAttempt.created_at < end,
            ~exists().where(TopUpCharge.version_attempt_id == VersionAttempt.id),
        )
    )
    return result.scalar_one()


async def store_planned_brief(
    db: AsyncSession, *, user_id: str, text: str, planned: PlannedBrief, now: datetime
) -> Idea:
    """
    Store the Brief as it was planned, with its single-post Idea and its split Ideas in posting
    order, and return the single-post Idea. Flushes.
    """
    single = Idea(posting_order=1, whole_brief=True, plan=planned.single)
    split = [
        Idea(posting_order=order, whole_brief=False, plan=plan)
        for order, plan in enumerate(planned.split, start=1)
    ]
    brief = Brief(
        user_id=user_id,
        text=text,
        created_at=now,
        positioning=planned.positioning,
        planning_reasoning=planned.reasoning,
        planning_model=planned.model,
        planning_usage=planned.usage,
        ideas=[single, *split],
    )
    db.add(brief)
    await db.flush()
    return single


async def create_post(db: AsyncSession, *, user_id: str, idea: Idea, now: datetime) -> Post:
    """
    A Post of `user_id`, who must be the User of the Idea's Brief, in its writing state until its
    first Version is recorded. Flushes.
    """
    post = Post(
        user_id=user_id,
        idea=idea,
        created_at=now,
        writing_since=now,
        # Set empty so the collection never loads lazily, which an async session can't do.
        text_media=[],
    )
    db.add(post)
    await db.flush()
    return post


async def record_version(
    db: AsyncSession,
    *,
    post: Post,
    sequence: int,
    version_number: int,
    feedback: Optional[str],
    written: WrittenVersion,
    now: datetime,
    starting_text: Optional[StartingText] = None,
) -> VersionAttempt:
    """Store a succeeded attempt, a Version, and make it the Post's Text, free to change. Flushes."""
    attempt = VersionAttempt(
        post_id=post.id,
        sequence=sequence,
        feedback=feedback,
        format=written.format,
        status=ATTEMPT_SUCCEEDED,
        version_number=version_number,
        sketch_parts=written.sketch_parts,
        parts=written.parts,
        first_reply=written.first_reply,
        sketch_model=written.sketch_model,
        humanizing_model=written.humanizing_model,
        sketch_usage=written.sketch_usage,
        humanizing_usage=written.humanizing_usage,
        hook_reasoning=written.hook.reasoning if written.hook else None,
        hook_name=written.hook.name if written.hook else None,
        hook_levers=written.hook_levers,
        hook_types=written.hook_types,
        cta_type=written.cta_type,
        sketches=written.sketches,
        merge=written.merge,
        starting_text_format=starting_text.format if starting_text else None,
        starting_text_parts=list(starting_text.parts) if starting_text else None,
        starting_text_version_number=starting_text.version_number if starting_text else None,
        starting_text_first_reply=starting_text.first_reply if starting_text else False,
        created_at=now,
    )
    db.add(attempt)
    set_text_from_version(post, attempt)
    post.writing_since = None
    await db.flush()
    return attempt


def set_text_from_version(post: Post, version: VersionAttempt) -> None:
    """
    Make the Version the Post's words, as written. The Text's Media stays on its Parts, and that of
    Parts the Version lacks moves onto its last Part. Not flushed.
    """
    post.text_format = version.format
    post.text_parts = list(version.parts or [])
    post.text_first_reply = version.first_reply
    post.text_version_number = version.version_number
    post.text_edited = False
    media.move_dropped_parts_media(post)


class VersionBeingWritten(ConflictError):
    pass


def check_not_writing(post: Post, *, now: datetime) -> None:
    """
    Refuses while Feedback's Version is being written, since the Version replaces the Text: an
    edit, a restore or other Feedback made meanwhile would be lost.
    """
    if is_writing(post, now=now):
        raise VersionBeingWritten(
            "Pumpkit is writing a new version of this post. Try again once it's written."
        )


def start_writing(post: Post, *, now: datetime) -> None:
    """Holds the Text until the Version is recorded, or its attempt fails. Not flushed."""
    check_not_writing(post, now=now)
    post.writing_since = now


class TextShapeKept(ConflictError):
    pass


def edit_text(post: Post, parts: list[str], *, first_reply: Optional[bool] = None) -> None:
    """
    Replace the Text's Parts with the User's, as typed. The Format and the number of Parts stay,
    since only Feedback changes them, except that a single post's first reply may be added or
    removed. `first_reply` None keeps the Text's. The Text reads as edited while it differs from
    its Version. Not flushed.
    """
    current = post.text_parts
    if current is None:
        raise ConflictError("This post has no text to edit. Start a new post.")
    if first_reply is None:
        first_reply = post.text_first_reply
    elif first_reply and post.text_format != FORMAT_POST:
        raise TextShapeKept("Only a single post has a first reply.")
    if first_reply != post.text_first_reply:
        expected = 1 + first_reply
    else:
        expected = len(current)
    if len(parts) != expected:
        if post.text_format != FORMAT_POST:
            why = (
                f"Editing keeps the text's {len(current)} parts. Give feedback to change its shape."
            )
        elif first_reply:
            why = (
                "Editing keeps the post and its first reply. Remove the first reply to save the "
                "post alone."
            )
        else:
            why = "Editing keeps the text a single post. Give feedback to make it a thread."
        raise TextShapeKept(why)
    version = next((a for a in post.attempts if a.version_number == post.text_version_number), None)
    post.text_parts = list(parts)
    post.text_first_reply = first_reply
    post.text_edited = (
        version is None or version.parts != parts or version.first_reply != first_reply
    )
    media.move_dropped_parts_media(post)


async def record_failed_attempt(
    db: AsyncSession,
    *,
    post: Post,
    sequence: int,
    feedback: Optional[str],
    format: Format,
    error: str,
    now: datetime,
) -> VersionAttempt:
    """Lets the Text change again. Flushes."""
    attempt = VersionAttempt(
        post_id=post.id,
        sequence=sequence,
        feedback=feedback,
        format=format,
        status=ATTEMPT_FAILED,
        error=error,
        created_at=now,
    )
    db.add(attempt)
    post.writing_since = None
    await db.flush()
    return attempt
