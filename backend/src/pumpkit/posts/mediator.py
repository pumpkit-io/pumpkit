from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO, Literal, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import pumpkit.auth.service.users as users_service
from pumpkit.auth.models import User
from pumpkit.core.background import TaskRegistry
from pumpkit.core.errors import (
    AppError,
    ConflictError,
    NotFoundError,
    RefusedError,
    report_background_exception,
)
from pumpkit.core.llm import LLM
from pumpkit.core.storage import FileStorage
from pumpkit.core.time import Clock, as_utc
from pumpkit.positioning import service as positioning_service
from pumpkit.posts import media as media_service
from pumpkit.posts import service
from pumpkit.posts.media_files import PREVIEW_CONTENT_TYPE
from pumpkit.posts.models import Post
from pumpkit.posts.plans import Plan
from pumpkit.posts.schemas import PostResponse
from pumpkit.posts.version_writing import (
    char_limit_for,
    charge_generation,
    check_attempt_limit,
    check_generation_left,
    plan_response,
    record_failed_attempt,
    user_post,
)
from pumpkit.posts.writing.planning import plan_brief
from pumpkit.posts.writing.post_writing import write_planned_version
from pumpkit.posts.writing_state import WRITING, writing_state

# Where the User saves their Positioning.
PERSONA_PAGE = "/persona"


async def start_post(
    db: AsyncSession,
    llm: LLM,
    tasks: TaskRegistry,
    sessions: async_sessionmaker[AsyncSession],
    user: User,
    brief: str,
    clock: Clock,
) -> PostResponse:
    """
    Plan the Brief with the User's Positioning, store it with its Ideas and a Post of its
    single-post Idea in its writing state, and start writing that Post's first Version in the
    background, as a single post or a Thread. Answers once the Post is stored; a failed plan
    stores nothing.
    """
    user_id = user.id
    now = clock()
    positioning = await positioning_service.get_positioning(db, user_id=user_id)
    if positioning is None:
        raise RefusedError("Set up your persona before writing a post.", fix_page=PERSONA_PAGE)
    await check_attempt_limit(db, user_id=user_id, now=now)
    await check_generation_left(db, user_id=user_id, now=now)
    char_limit = await char_limit_for(db, user_id=user_id)
    # Ends the read transaction before the plan call, which can take a minute.
    await db.commit()

    planned = await plan_brief(
        llm,
        user_id=user_id,
        brief=brief,
        positioning=positioning.text,
        char_limit=char_limit,
    )

    idea = await service.store_planned_brief(
        db, user_id=user_id, text=brief, planned=planned, now=now
    )
    # Read again: the write's timeout counts from after the plan call, not from the request.
    started_at = clock()
    post = await service.create_post(db, user_id=user_id, idea=idea, now=started_at)
    write = _FirstVersionWrite(
        user_id=user_id,
        post_id=post.id,
        started_at=started_at,
        brief=brief,
        positioning=positioning.text,
        plan=planned.single,
        char_limit=char_limit,
    )
    return await _start_first_version_write(db, llm, tasks, sessions, write, clock)


async def retry_post(
    db: AsyncSession,
    llm: LLM,
    tasks: TaskRegistry,
    sessions: async_sessionmaker[AsyncSession],
    user: User,
    post_id: str,
    clock: Clock,
) -> PostResponse:
    """
    Write the first Version of a Post Pumpkit couldn't write again, from its Idea's Plan and the
    Positioning its Brief was planned with, in the background. Counts as a new attempt.
    """
    now = clock()
    post = await user_post(db, user=user, post_id=post_id, for_update=True)
    state = writing_state(post, now=now)
    if state == WRITING:
        raise ConflictError("Pumpkit is still writing this post.")
    if state is None:
        raise ConflictError("This post is already written.")
    plan, positioning = post.idea.plan, post.idea.brief.positioning
    if plan is None or positioning is None:
        raise ConflictError(
            "This post was started before plans existed, so it can't be written again. "
            "Start a new post."
        )
    await check_attempt_limit(db, user_id=user.id, now=now)
    await check_generation_left(db, user_id=user.id, now=now)
    char_limit = await char_limit_for(db, user_id=user.id)
    service.start_writing(post, now=now)
    write = _FirstVersionWrite(
        user_id=user.id,
        post_id=post.id,
        started_at=now,
        brief=post.brief,
        positioning=positioning,
        plan=plan,
        char_limit=char_limit,
    )
    return await _start_first_version_write(db, llm, tasks, sessions, write, clock)


async def _start_first_version_write(
    db: AsyncSession,
    llm: LLM,
    tasks: TaskRegistry,
    sessions: async_sessionmaker[AsyncSession],
    write: "_FirstVersionWrite",
    clock: Clock,
) -> PostResponse:
    """Commit the Post in its writing state, then start the write and answer with the Post."""
    response = PostResponse(
        id=write.post_id,
        brief=write.brief,
        plan=plan_response(write.plan),
        versions=[],
        writing_state=WRITING,
    )
    await db.commit()
    await tasks.start(_task_name(write.post_id), _write_first_version(write, llm, sessions, clock))
    return response


def _task_name(post_id: str) -> str:
    return f"write the first version of {post_id}"


@dataclass(frozen=True)
class _FirstVersionWrite:
    """What writing a Post's first Version needs, read before the request answers."""

    user_id: str
    post_id: str
    # The Post's `writing_since` for this write: a later Retry changes it, and this write is dropped.
    started_at: datetime
    brief: str
    positioning: str
    plan: Plan
    char_limit: int


async def _write_first_version(
    write: _FirstVersionWrite,
    llm: LLM,
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
) -> None:
    """
    The background task: the model calls with no session open, then the Version and its charge,
    or the failed attempt, in a session of its own.
    """
    try:
        written = await write_planned_version(
            llm,
            brief=write.brief,
            positioning=write.positioning,
            plan=write.plan,
            char_limit=write.char_limit,
            user_id=write.user_id,
        )
    except Exception as error:
        async with sessions() as db:
            post = await _post_still_writing(db, write)
            if post is not None:
                await record_failed_attempt(
                    db,
                    post=post,
                    sequence=len(post.attempts) + 1,
                    feedback=None,
                    format=write.plan.format,
                    error=error,
                    now=clock(),
                )
                await db.commit()
        if not isinstance(error, AppError) or error.reported:
            report_background_exception(_task_name(write.post_id), error)
        return

    async with sessions() as db:
        # Before the Post: its key share on the User deadlocks two writes upgrading it to charge.
        await users_service.lock_user_id(db, user_id=write.user_id)
        post = await _post_still_writing(db, write)
        if post is None:
            return
        now = clock()
        version = await service.record_version(
            db,
            post=post,
            sequence=len(post.attempts) + 1,
            version_number=1,
            feedback=None,
            written=written,
            now=now,
        )
        await charge_generation(db, user_id=write.user_id, version=version, now=now)
        await db.commit()


async def _post_still_writing(db: AsyncSession, write: _FirstVersionWrite) -> Optional[Post]:
    """The Post, locked, unless it was deleted or a Retry started another write of it."""
    post = await service.get_user_post(
        db, user_id=write.user_id, post_id=write.post_id, for_update=True
    )
    if post is None or post.writing_since is None:
        return None
    if as_utc(post.writing_since) != write.started_at:
        return None
    return post


@dataclass(frozen=True)
class StoredFile:
    """An open file the caller streams and closes."""

    file: BinaryIO
    content_type: str


async def open_media_file(
    db: AsyncSession,
    storage: FileStorage,
    user: User,
    media_id: str,
    which: Literal["preview", "file"],
) -> StoredFile:
    """The preview or the file of the User's Media, open for reading."""
    media = await media_service.get_user_media(db, user_id=user.id, media_id=media_id)
    if media is None:
        raise NotFoundError("Media not found.")
    if which == "preview":
        key, content_type = media.preview_key, PREVIEW_CONTENT_TYPE
    else:
        key, content_type = media.file_key, media.content_type
    if key is None:
        raise NotFoundError("This media's file isn't kept any more.")
    # Ends the read transaction, so no connection stays held while the file streams.
    await db.commit()
    return StoredFile(file=await storage.open(key), content_type=content_type)
