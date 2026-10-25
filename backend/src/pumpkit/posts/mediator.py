from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.core.errors import ConflictError, NotFoundError, RefusedError, RetryLaterError
from pumpkit.core.time import as_utc
from pumpkit.posts import service
from pumpkit.posts.formats import FORMAT_POST, Format, part_char_count, part_char_limit
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


def version_response(attempt: VersionAttempt) -> VersionResponse:
    assert attempt.version_number is not None and attempt.draft_parts is not None
    assert attempt.final_parts is not None and attempt.slop_tells is not None
    format = attempt.format
    return VersionResponse(
        id=attempt.id,
        number=attempt.version_number,
        feedback=attempt.feedback,
        format=format,
        draft_parts=attempt.draft_parts,
        parts=[
            PartResponse(
                text=text,
                char_count=part_char_count(format, text),
                char_limit=part_char_limit(format),
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
    return PostResponse(
        id=post.id, brief=post.brief, versions=[version_response(v) for v in _versions(post)]
    )


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
    # Ends the read transaction before the calls, which can take minutes.
    await db.commit()

    try:
        written = await write_first_version(llm, corpus, brief, format)
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
    return PostResponse(id=post.id, brief=post.brief, versions=[version_response(version)])


async def add_version(
    db: AsyncSession, llm: LLM, user: User, post_id: str, feedback: str, now: datetime
) -> VersionResponse:
    """
    Write the next Version of the User's Post from Feedback, with the corpus the Post started
    with. Stored after the calls like `start_post`, and a failure likewise.
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
    sequence = len(post.attempts) + 1
    # Ends the read transaction before the calls, which can take minutes.
    await db.commit()

    try:
        written = await write_next_version(llm, corpus, post.brief, earlier, feedback)
    except Exception as error:
        await _keep_failed_attempt(
            db,
            post=post,
            sequence=sequence,
            feedback=feedback,
            format=FORMAT_POST,
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
    return version_response(version)
