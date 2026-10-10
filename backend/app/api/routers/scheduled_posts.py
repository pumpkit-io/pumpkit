from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.scheduled_posts as scheduled_posts_mediator
from app.api.dependencies import get_current_user, require_subscribed_user
from app.core.clock import Clock, get_clock
from app.core.rate_limit import limiter
from app.core.x_publisher import XPublisher, get_x_publisher
from app.db.models import User
from app.db.session import get_async_db
from app.schemas.scheduled_posts import (
    ScheduledPostCreateRequest,
    ScheduledPostResponse,
    ScheduledPostsListResponse,
)

router = APIRouter(tags=["scheduled-posts"])


# Open to Users who aren't Subscribed, so their Published and Failed history stays visible.
@router.get(
    "/scheduled-posts",
    response_model=ScheduledPostsListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_scheduled_posts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> ScheduledPostsListResponse:
    return await scheduled_posts_mediator.list_scheduled_posts(db=db, user=current_user)


@router.post(
    "/scheduled-posts",
    response_model=ScheduledPostResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/minute")
async def create_scheduled_post(
    request: Request,
    create_request: ScheduledPostCreateRequest,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    publisher: XPublisher = Depends(get_x_publisher),
    clock: Clock = Depends(get_clock),
) -> ScheduledPostResponse:
    """Publishes on X before answering: the Scheduled post comes back Published or Failed."""
    return await scheduled_posts_mediator.post_now(
        db=db, publisher=publisher, user=current_user, text=create_request.text, now=clock()
    )
