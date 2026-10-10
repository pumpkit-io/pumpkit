from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.posts as posts_service
from app.core.llm import LLM
from app.core.retry_later import RetryLaterError
from app.db.models import ATTEMPT_SUCCEEDED, Post, User, VersionAttempt
from app.schemas.posts import PostResponse, TellResponse, VersionResponse
from app.writing.constants import POST_MAX_CHARS
from app.writing.versions import EarlierVersion, write_first_version, write_next_version

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


async def _check_attempt_limit(db: AsyncSession, *, user_id: str, now: datetime) -> None:
    attempted_at = await posts_service.attempt_times_since(
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
    error: Exception,
    now: datetime,
) -> None:
    await posts_service.record_failed_attempt(
        db,
        post=post,
        sequence=sequence,
        feedback=feedback,
        error=f"{type(error).__name__}: {error}",
        now=now,
    )
    # Commit before the caller re-raises, or the request session rolls the failed attempt back.
    await db.commit()


def version_response(attempt: VersionAttempt) -> VersionResponse:
    assert attempt.version_number is not None and attempt.draft is not None
    assert attempt.final is not None and attempt.final_char_count is not None
    assert attempt.slop_tells is not None
    return VersionResponse(
        id=attempt.id,
        number=attempt.version_number,
        feedback=attempt.feedback,
        draft=attempt.draft,
        final=attempt.final,
        final_char_count=attempt.final_char_count,
        final_char_limit=POST_MAX_CHARS,
        tells=[TellResponse(**tell) for tell in attempt.slop_tells],
    )


async def start_post(
    db: AsyncSession, llm: LLM, user: User, brief: str, now: datetime
) -> PostResponse:
    """
    Start a Post from the Brief and write its first Version.

    The Post and its attempt are stored only after the calls, so no transaction stays open
    across them; a failure is stored as a failed attempt before the error is re-raised.
    """
    user_id = user.id
    corpus = await posts_service.corpus_for_user(db, user_id=user_id)
    if not corpus.post_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Add an Inspiration author with posts before writing a Post.",
        )
    await _check_attempt_limit(db, user_id=user_id, now=now)
    # Ends the read transaction before the calls, which can take minutes.
    await db.commit()

    try:
        written = await write_first_version(llm, corpus, brief)
    except Exception as error:
        post = await posts_service.create_post(
            db, user_id=user_id, brief=brief, corpus=corpus, now=now
        )
        await _keep_failed_attempt(db, post=post, sequence=1, feedback=None, error=error, now=now)
        raise

    post = await posts_service.create_post(db, user_id=user_id, brief=brief, corpus=corpus, now=now)
    version = await posts_service.record_version(
        db, post=post, sequence=1, version_number=1, feedback=None, written=written, now=now
    )
    await db.commit()
    return PostResponse(id=post.id, brief=post.brief, versions=[version_response(version)])


async def add_version(
    db: AsyncSession, llm: LLM, user: User, post_id: str, feedback: str, now: datetime
) -> VersionResponse:
    """
    Write the next Version of the User's Post from Feedback, with the corpus the Post started
    with. Stored after the calls like `start_post`, and a failure likewise.
    """
    post = await posts_service.get_user_post(db, user_id=user.id, post_id=post_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    versions = [attempt for attempt in post.attempts if attempt.status == ATTEMPT_SUCCEEDED]
    if not versions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Post has no Version to give Feedback on. Start a new Post.",
        )
    await _check_attempt_limit(db, user_id=user.id, now=now)
    corpus = await posts_service.corpus_for_post(db, post=post)
    earlier = [EarlierVersion(feedback=v.feedback, final=v.final or "") for v in versions]
    sequence = len(post.attempts) + 1
    # Ends the read transaction before the calls, which can take minutes.
    await db.commit()

    try:
        written = await write_next_version(llm, corpus, post.brief, earlier, feedback)
    except Exception as error:
        await _keep_failed_attempt(
            db, post=post, sequence=sequence, feedback=feedback, error=error, now=now
        )
        raise

    version = await posts_service.record_version(
        db,
        post=post,
        sequence=sequence,
        version_number=len(versions) + 1,
        feedback=feedback,
        written=written,
        now=now,
    )
    await db.commit()
    return version_response(version)
