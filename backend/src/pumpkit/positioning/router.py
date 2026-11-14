from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.billing.dependencies import require_subscribed_user
from pumpkit.core.db.session import get_async_db
from pumpkit.core.rate_limit import limiter
from pumpkit.core.time import Clock, get_clock
from pumpkit.positioning import mediator
from pumpkit.positioning.schemas import WRITE_RATE, PositioningResponse, PositioningSaveRequest

router = APIRouter(tags=["positioning"])


@router.get("/positioning", response_model=PositioningResponse, status_code=status.HTTP_200_OK)
async def get_positioning(
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
) -> PositioningResponse:
    return await mediator.get_positioning(db, current_user)


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
