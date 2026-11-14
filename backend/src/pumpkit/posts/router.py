from collections.abc import Iterator
from typing import BinaryIO

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.billing.dependencies import require_subscribed_user
from pumpkit.core.db.session import get_async_db
from pumpkit.core.llm import LLM, get_llm
from pumpkit.core.rate_limit import limiter
from pumpkit.core.storage import FileStorage, get_file_storage
from pumpkit.core.time import Clock, get_clock
from pumpkit.posts import mediator
from pumpkit.posts.schemas import WRITE_RATE, PostResponse, PostStartRequest

# Feedback on a Post is served from scheduling, which knows whether the Post takes it.
router = APIRouter(tags=["posts"])


@router.post("/posts", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(WRITE_RATE)
async def start_post(
    request: Request,
    start_request: PostStartRequest,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    llm: LLM = Depends(get_llm),
    clock: Clock = Depends(get_clock),
) -> PostResponse:
    """Plans the Brief and writes the first Version before answering, which takes a few minutes."""
    return await mediator.start_post(
        db=db,
        llm=llm,
        user=current_user,
        brief=start_request.brief,
        now=clock(),
    )


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
