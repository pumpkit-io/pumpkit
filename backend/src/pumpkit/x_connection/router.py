from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.auth.schemas import UserProfileResponse
from pumpkit.billing.dependencies import require_subscribed_user
from pumpkit.core.db.session import get_async_db
from pumpkit.core.photos import PhotoFetcher, get_photo_fetcher
from pumpkit.core.rate_limit import limiter
from pumpkit.core.time import Clock, get_clock
from pumpkit.x_connection import mediator
from pumpkit.x_connection.schemas import XAuthorizationStartResponse
from pumpkit.x_connection.x_publisher import XPublisher, get_x_publisher

# GET /x-connection and completing an authorization answer with the Scheduled posts waiting,
# so the Scheduled posts router serves them.
router = APIRouter(tags=["x-connection"])


@router.post(
    "/x-connection/authorizations",
    response_model=XAuthorizationStartResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("10/minute")
async def start_x_authorization(
    request: Request,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    publisher: XPublisher = Depends(get_x_publisher),
    clock: Clock = Depends(get_clock),
) -> XAuthorizationStartResponse:
    return await mediator.start_authorization(
        db=db, publisher=publisher, user=current_user, now=clock()
    )


@router.delete("/x-connection", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_x(
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    publisher: XPublisher = Depends(get_x_publisher),
) -> None:
    await mediator.disconnect(db=db, publisher=publisher, user=current_user)


@router.post(
    "/x-connection/photo/use",
    response_model=UserProfileResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("10/minute")
async def use_x_photo(
    request: Request,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    photo_fetcher: PhotoFetcher = Depends(get_photo_fetcher),
    clock: Clock = Depends(get_clock),
) -> UserProfileResponse:
    return await mediator.use_photo(
        db=db, photo_fetcher=photo_fetcher, user=current_user, now=clock()
    )


@router.post("/x-connection/photo/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline_x_photo(
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> None:
    await mediator.decline_photo(db=db, user=current_user, now=clock())
