from collections.abc import Iterator
from typing import BinaryIO

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pumpkit.auth.models import User
from pumpkit.billing.dependencies import require_subscribed_user
from pumpkit.core.background import TaskRegistry, get_background_tasks
from pumpkit.core.db.session import get_async_db, get_session_maker
from pumpkit.core.llm import LLM, get_llm
from pumpkit.core.rate_limit import limiter
from pumpkit.core.storage import FileStorage, get_file_storage
from pumpkit.core.time import Clock, get_clock
from pumpkit.posts import mediator
from pumpkit.posts.schemas import (
    WRITE_RATE,
    BriefRequest,
    BriefResponse,
    PostResponse,
    WriteIdeasRequest,
)

# Feedback on a Post is served from scheduling, which knows whether the Post takes it.
router = APIRouter(tags=["posts"])


@router.post("/briefs", response_model=BriefResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(WRITE_RATE)
async def plan_brief(
    request: Request,
    brief_request: BriefRequest,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    llm: LLM = Depends(get_llm),
    tasks: TaskRegistry = Depends(get_background_tasks),
    sessions: async_sessionmaker[AsyncSession] = Depends(get_session_maker),
    clock: Clock = Depends(get_clock),
) -> BriefResponse:
    """
    Plans the Brief and answers with it and its Ideas. With no split Ideas, the single-post Idea's
    Post is already being written in the background, which `GET /posts/{post_id}` shows when it ends.
    """
    return await mediator.plan_brief(
        db=db,
        llm=llm,
        tasks=tasks,
        sessions=sessions,
        user=current_user,
        brief=brief_request.brief,
        clock=clock,
    )


@router.post(
    "/briefs/{brief_id}/posts",
    response_model=BriefResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(WRITE_RATE)
async def write_ideas(
    request: Request,
    brief_id: str,
    write_request: WriteIdeasRequest,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    llm: LLM = Depends(get_llm),
    tasks: TaskRegistry = Depends(get_background_tasks),
    sessions: async_sessionmaker[AsyncSession] = Depends(get_session_maker),
    clock: Clock = Depends(get_clock),
) -> BriefResponse:
    """Starts writing a Post of each Idea named, in the background, and answers with the Brief."""
    return await mediator.write_ideas(
        db=db,
        llm=llm,
        tasks=tasks,
        sessions=sessions,
        user=current_user,
        brief_id=brief_id,
        idea_ids=write_request.idea_ids,
        clock=clock,
    )


@router.post(
    "/posts/{post_id}/retry", response_model=PostResponse, status_code=status.HTTP_202_ACCEPTED
)
@limiter.limit(WRITE_RATE)
async def retry_post(
    request: Request,
    post_id: str,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    llm: LLM = Depends(get_llm),
    tasks: TaskRegistry = Depends(get_background_tasks),
    sessions: async_sessionmaker[AsyncSession] = Depends(get_session_maker),
    clock: Clock = Depends(get_clock),
) -> PostResponse:
    """Writes the first Version of a Post Pumpkit couldn't write again, in the background."""
    return await mediator.retry_post(
        db=db,
        llm=llm,
        tasks=tasks,
        sessions=sessions,
        user=current_user,
        post_id=post_id,
        clock=clock,
    )


@router.delete("/posts/{post_id}/failed-feedback", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_failed_feedback(
    post_id: str,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> None:
    """Stops showing the Post's last Feedback as failed; a Feedback still being written stays."""
    await mediator.dismiss_failed_feedback(db, user=current_user, post_id=post_id, now=clock())


_CHUNK_BYTES = 256 * 1024
# A Media's preview and file never change under its id.
_MEDIA_HEADERS = {"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"}


def _chunks(file: BinaryIO) -> Iterator[bytes]:
    with file:
        while chunk := file.read(_CHUNK_BYTES):
            yield chunk


@router.get("/media/{media_id}/preview", response_class=StreamingResponse)
async def get_media_preview(
    media_id: str,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    storage: FileStorage = Depends(get_file_storage),
) -> StreamingResponse:
    """The small image the web app shows for the User's Media, kept after it is published."""
    stored = await mediator.open_media_file(db, storage, current_user, media_id, "preview")
    return StreamingResponse(
        _chunks(stored.file), media_type=stored.content_type, headers=_MEDIA_HEADERS
    )


@router.get("/media/{media_id}/file", response_class=StreamingResponse)
async def get_media_file(
    media_id: str,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    storage: FileStorage = Depends(get_file_storage),
) -> StreamingResponse:
    """The User's Media as attached, until it is published."""
    stored = await mediator.open_media_file(db, storage, current_user, media_id, "file")
    return StreamingResponse(
        _chunks(stored.file), media_type=stored.content_type, headers=_MEDIA_HEADERS
    )
