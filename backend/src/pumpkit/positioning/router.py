from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pumpkit.auth.dependencies import get_current_user
from pumpkit.auth.models import User
from pumpkit.authors.x_reader import XReader, get_x_reader
from pumpkit.billing.dependencies import require_subscribed_user
from pumpkit.core.background import TaskRegistry, get_background_tasks
from pumpkit.core.db.session import get_async_db, get_session_maker
from pumpkit.core.llm import LLM, get_llm
from pumpkit.core.rate_limit import limiter
from pumpkit.core.time import Clock, get_clock
from pumpkit.positioning import mediator
from pumpkit.positioning.schemas import (
    WRITE_RATE,
    PositioningPageResponse,
    PositioningResponse,
    PositioningSaveRequest,
)

router = APIRouter(tags=["positioning"])


@router.get("/positioning", response_model=PositioningPageResponse, status_code=status.HTTP_200_OK)
async def get_positioning(
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> PositioningPageResponse:
    return await mediator.get_positioning_page(db, current_user, clock())


@router.put("/positioning", response_model=PositioningResponse, status_code=status.HTTP_200_OK)
@limiter.limit(WRITE_RATE)
async def save_positioning(
    request: Request,
    save_request: PositioningSaveRequest,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> PositioningResponse:
    return await mediator.save_positioning(db, current_user, save_request.text, clock())


@router.post("/positioning/draft/start", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(WRITE_RATE)
async def start_positioning_draft(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    reader: XReader = Depends(get_x_reader),
    llm: LLM = Depends(get_llm),
    tasks: TaskRegistry = Depends(get_background_tasks),
    sessions: async_sessionmaker[AsyncSession] = Depends(get_session_maker),
    clock: Clock = Depends(get_clock),
) -> Response:
    """
    Starts drafting the User's Positioning in the background and answers at once, Subscribed or
    not, so the sign-in callback page can start it (ADR 0030). `GET /positioning` shows the draft.
    """
    await mediator.start_draft(db, reader, llm, tasks, sessions, current_user, clock)
    return Response(status_code=status.HTTP_202_ACCEPTED)
