from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.x_connection as x_connection_mediator
from app.api.dependencies import get_current_user, require_subscribed_user
from app.core.clock import Clock, get_clock
from app.core.rate_limit import limiter
from app.core.x_publisher import XPublisher, get_x_publisher
from app.db.models import User
from app.db.session import get_async_db
from app.schemas.x_connection import (
    XAuthorizationCompleteRequest,
    XAuthorizationStartResponse,
    XConnectionResponse,
)

router = APIRouter(tags=["x-connection"])


@router.get("/x-connection", response_model=XConnectionResponse, status_code=status.HTTP_200_OK)
async def get_x_connection(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> XConnectionResponse:
    return await x_connection_mediator.get_connection(db=db, user=current_user)


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
    return await x_connection_mediator.start_authorization(
        db=db, publisher=publisher, user=current_user, now=clock()
    )


@router.post(
    "/x-connection/authorizations/complete",
    response_model=XConnectionResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("10/minute")
async def complete_x_authorization(
    request: Request,
    complete_request: XAuthorizationCompleteRequest,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    publisher: XPublisher = Depends(get_x_publisher),
    clock: Clock = Depends(get_clock),
) -> XConnectionResponse:
    return await x_connection_mediator.complete_authorization(
        db=db,
        publisher=publisher,
        user=current_user,
        code=complete_request.code,
        state=complete_request.state,
        now=clock(),
    )


# Open to Users who aren't Subscribed: ending Pumpkit's access to X never needs a Subscription.
@router.delete("/x-connection", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_x(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    publisher: XPublisher = Depends(get_x_publisher),
) -> None:
    await x_connection_mediator.disconnect(db=db, publisher=publisher, user=current_user)
