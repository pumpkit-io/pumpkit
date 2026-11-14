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
from pumpkit.posts.models import Brief, Idea, Post
from pumpkit.posts.plan_calls import count_plan_call
from pumpkit.posts.plans import Plan
from pumpkit.posts.schemas import BriefPostResponse, BriefResponse, IdeaResponse, PostResponse
from pumpkit.posts.version_writing import (
    char_limit_for,
    charge_generation,
    check_attempt_limit,
    check_generation_left,
    plan_response,
    post_still_writing,
    record_failed_attempt,
    text_response,
    user_post,
)
from pumpkit.posts.writing.planning import plan_brief as plan_with_model
from pumpkit.posts.writing.post_writing import write_planned_version
from pumpkit.posts.writing.versions import WrittenVersion
from pumpkit.posts.writing_state import WRITING, writing_state

# Where the User saves their Positioning.
PERSONA_PAGE = "/persona"


async def plan_brief(
    db: AsyncSession,
    llm: LLM,
    tasks: TaskRegistry,
    sessions: async_sessionmaker[AsyncSession],
    user: User,
    brief: str,
    clock: Clock,
) -> BriefResponse:
    """
    Plan the Brief with the User's Positioning and store it with its Ideas. A Brief with no split
    Ideas also starts writing its single-post Idea in the background, so the simple case stays one
    request; with split Ideas nothing is written until the User picks. A failed plan stores nothing.
    """
    planned = await _plan_and_store(db, llm, user, brief, clock)
    posts: dict[str, Post] = {}
    writes = []
    if len(planned.brief.ideas) == 1:
        write = await _create_post(db, planned, planned.brief.ideas[0], now=clock())
        posts[write.idea_id] = write.post
        writes.append(write.write)
    response = _brief_response(planned.brief, posts, planned.char_limit, now=clock())
    await _start_writes(db, llm, tasks, sessions, writes, clock)
    return response


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
    Plan the Brief as `plan_brief` does, then start writing its single-post Idea, which covers the
    whole Brief, whether or not the planner split it. The split Ideas stay on the Brief, unwritten.
    """
    planned = await _plan_and_store(db, llm, user, brief, clock)
    single = planned.brief.ideas[0]
    created = await _create_post(db, planned, single, now=clock())
    write = created.write
    await _start_writes(db, llm, tasks, sessions, [write], clock)
    return PostResponse(
        id=write.post_id,
        brief=write.brief,
        plan=plan_response(write.plan),
        versions=[],
        writing_state=WRITING,
    )


@dataclass(frozen=True)
class _PlannedBrief:
    """A Brief just planned and stored, with what writing its Ideas needs."""

    brief: Brief
    char_limit: int


async def _plan_and_store(
    db: AsyncSession, llm: LLM, user: User, brief: str, clock: Clock
) -> _PlannedBrief:
    """
    The plan call, with no transaction open across it, then the Brief and its Ideas, flushed.
    Refused up front when the User couldn't write even one Post, or is at the cap on plan calls.
    """
    user_id = user.id
    now = clock()
    positioning = await positioning_service.get_positioning(db, user_id=user_id)
    if positioning is None:
        raise RefusedError("Set up your persona before writing a post.", fix_page=PERSONA_PAGE)
    await check_attempt_limit(db, user_id=user_id, now=now)
    await check_generation_left(db, user_id=user_id, now=now)
    char_limit = await char_limit_for(db, user_id=user_id)
    await count_plan_call(db, user_id=user_id, now=now)
    # Ends the transaction and the User's lock before the plan call, which can take a minute.
    await db.commit()

    planned = await plan_with_model(
        llm,
        user_id=user_id,
        brief=brief,
        positioning=positioning.text,
        char_limit=char_limit,
    )

    stored = await service.store_planned_brief(
        db, user_id=user_id, text=brief, planned=planned, now=now
    )
    return _PlannedBrief(brief=stored, char_limit=char_limit)


async def write_ideas(
    db: AsyncSession,
    llm: LLM,
    tasks: TaskRegistry,
    sessions: async_sessionmaker[AsyncSession],
    user: User,
    brief_id: str,
    idea_ids: list[str],
    clock: Clock,
) -> BriefResponse:
    """
    Start writing a Post of each Idea named, split or single-post, in parallel in the background,
    once the hourly attempt limit and the Generations left have room for all of them. Refuses all
    of them, writing none, when one is already written or there isn't room.
    """
    if not idea_ids:
        raise RefusedError("Pick at least one idea to write.")
    user_id = user.id
    now = clock()
    # Serializes the User's requests, so two can't both write one Idea or take the last Generation.
    await users_service.lock_user_id(db, user_id=user_id)
    brief = await _user_brief(db, user=user, brief_id=brief_id)
    wanted = set(idea_ids)
    if not wanted <= {idea.id for idea in brief.ideas}:
        raise NotFoundError("Idea not found.")
    picked = [idea for idea in brief.ideas if idea.id in wanted]
    posts = await service.posts_of_ideas(db, idea_ids=[idea.id for idea in brief.ideas])
    if any(idea.id in posts for idea in picked):
        raise ConflictError("One of these ideas is already written.")
    if brief.positioning is None or any(idea.plan is None for idea in picked):
        raise ConflictError("This brief was never planned, so its ideas can't be written.")
    await check_attempt_limit(db, user_id=user_id, now=now, count=len(picked))
    await check_generation_left(db, user_id=user_id, now=now, count=len(picked))
    planned = _PlannedBrief(brief=brief, char_limit=await char_limit_for(db, user_id=user_id))
    writes = []
    for idea in picked:
        created = await _create_post(db, planned, idea, now=now)
        posts[idea.id] = created.post
        writes.append(created.write)
    response = _brief_response(brief, posts, planned.char_limit, now=now)
    await _start_writes(db, llm, tasks, sessions, writes, clock)
    return response


async def get_brief(db: AsyncSession, *, user: User, brief_id: str, now: datetime) -> BriefResponse:
    """The Brief with its Ideas and their Posts as they are now, for its page to poll."""
    brief = await _user_brief(db, user=user, brief_id=brief_id)
    posts = await service.posts_of_ideas(db, idea_ids=[idea.id for idea in brief.ideas])
    char_limit = await char_limit_for(db, user_id=user.id)
    return _brief_response(brief, posts, char_limit, now=now)


async def _user_brief(db: AsyncSession, *, user: User, brief_id: str) -> Brief:
    brief = await service.get_user_brief(db, user_id=user.id, brief_id=brief_id)
    if brief is None:
        raise NotFoundError("Brief not found.")
    return brief


def _brief_response(
    brief: Brief, posts: dict[str, Post], char_limit: int, *, now: datetime
) -> BriefResponse:
    def post_response(post: Optional[Post]) -> Optional[BriefPostResponse]:
        if post is None:
            return None
        return BriefPostResponse(
            id=post.id,
            writing_state=writing_state(post, now=now),
            text=text_response(post, char_limit),
        )

    return BriefResponse(
        id=brief.id,
        text=brief.text,
        created_at=as_utc(brief.created_at),
        ideas=[
            IdeaResponse(
                id=idea.id,
                posting_order=idea.posting_order,
                whole_brief=idea.whole_brief,
                plan=plan_response(idea.plan),
                post=post_response(posts.get(idea.id)),
            )
            for idea in brief.ideas
        ],
    )


@dataclass(frozen=True)
class _CreatedPost:
    idea_id: str
    post: Post
    write: "_FirstVersionWrite"


async def _create_post(
    db: AsyncSession, planned: _PlannedBrief, idea: Idea, *, now: datetime
) -> _CreatedPost:
    """A Post of the Idea in its writing state from `now`, and the write that will fill it."""
    brief = planned.brief
    plan = idea.plan
    assert plan is not None and brief.positioning is not None
    post = await service.create_post(db, user_id=brief.user_id, idea=idea, now=now)
    write = _FirstVersionWrite(
        user_id=brief.user_id,
        post_id=post.id,
        started_at=now,
        brief=brief.text,
        positioning=brief.positioning,
        plan=plan,
        char_limit=planned.char_limit,
    )
    return _CreatedPost(idea_id=idea.id, post=post, write=write)


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
    await _start_writes(db, llm, tasks, sessions, [write], clock)
    return PostResponse(
        id=write.post_id,
        brief=write.brief,
        plan=plan_response(write.plan),
        versions=[],
        writing_state=WRITING,
    )


async def _start_writes(
    db: AsyncSession,
    llm: LLM,
    tasks: TaskRegistry,
    sessions: async_sessionmaker[AsyncSession],
    writes: list["_FirstVersionWrite"],
    clock: Clock,
) -> None:
    """
    Commit the Posts in their writing state, then start one task per write. The tasks run in
    parallel, and `LLM_CALLS_IN_FLIGHT` caps their model calls across the Instance.
    """
    await db.commit()
    for write in writes:
        await tasks.start(
            _task_name(write.post_id), _write_first_version(write, llm, sessions, clock)
        )


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
    The background task: the model calls with no session open, then the Version and its charge in
    a session of its own, or else the failed attempt in a fresh one.
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
        await _record_first_version(write, written, sessions, clock)
    except Exception as error:
        try:
            await _record_failed_first_version(write, sessions, clock, error)
        finally:
            if not isinstance(error, AppError) or error.reported:
                report_background_exception(_task_name(write.post_id), error)


async def _record_first_version(
    write: _FirstVersionWrite,
    written: WrittenVersion,
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
) -> None:
    async with sessions() as db:
        # Before the Post: its key share on the User deadlocks two writes upgrading it to charge.
        await users_service.lock_user_id(db, user_id=write.user_id)
        now = clock()
        post = await post_still_writing(
            db, user_id=write.user_id, post_id=write.post_id, started_at=write.started_at, now=now
        )
        if post is None:
            return
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


async def _record_failed_first_version(
    write: _FirstVersionWrite,
    sessions: async_sessionmaker[AsyncSession],
    clock: Clock,
    error: Exception,
) -> None:
    async with sessions() as db:
        now = clock()
        post = await post_still_writing(
            db, user_id=write.user_id, post_id=write.post_id, started_at=write.started_at, now=now
        )
        if post is None:
            return
        await record_failed_attempt(
            db,
            post=post,
            sequence=len(post.attempts) + 1,
            feedback=None,
            format=write.plan.format,
            error=error,
            now=now,
        )
        await db.commit()


async def dismiss_failed_feedback(
    db: AsyncSession, *, user: User, post_id: str, now: datetime
) -> None:
    post = await user_post(db, user=user, post_id=post_id, for_update=True)
    service.dismiss_failed_feedback(post, now=now)
    await db.commit()


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
