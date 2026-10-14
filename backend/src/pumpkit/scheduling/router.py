from typing import Optional

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.dependencies import get_current_user
from pumpkit.auth.models import User
from pumpkit.authors.x_reader import XReader, get_x_reader
from pumpkit.billing.dependencies import require_subscribed_user
from pumpkit.core.db.session import get_async_db
from pumpkit.core.rate_limit import limiter
from pumpkit.core.time import Clock, get_clock
from pumpkit.scheduling import mediator
from pumpkit.scheduling.communities import Community
from pumpkit.scheduling.models import ScheduledPostState
from pumpkit.scheduling.schemas import (
    CommunityLookupRequest,
    CommunityResponse,
    ScheduledPostCreateRequest,
    ScheduledPostResponse,
    ScheduledPostsListResponse,
    ScheduledPostUpdateRequest,
    XConnectionResponse,
)
from pumpkit.x_connection.schemas import XAuthorizationCompleteRequest
from pumpkit.x_connection.x_publisher import XPublisher, get_x_publisher

router = APIRouter(tags=["scheduled-posts"])
# The X connection routes that answer with the Scheduled posts waiting. Two routers, so main.py
# can mount them around x_connection's router and keep the OpenAPI document's order.
x_connection_router = APIRouter(tags=["x-connection"])
x_authorization_router = APIRouter(tags=["x-connection"])


@x_connection_router.get(
    "/x-connection", response_model=XConnectionResponse, status_code=status.HTTP_200_OK
)
async def get_x_connection(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> XConnectionResponse:
    return await mediator.get_x_connection(db=db, user=current_user)


@x_authorization_router.post(
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
    return await mediator.complete_x_authorization(
        db=db,
        publisher=publisher,
        user=current_user,
        code=complete_request.code,
        state=complete_request.state,
        now=clock(),
    )


@router.post("/community-lookups", response_model=CommunityResponse, status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
async def look_up_community(
    request: Request,
    lookup_request: CommunityLookupRequest,
    current_user: User = Depends(require_subscribed_user),
    reader: XReader = Depends(get_x_reader),
) -> CommunityResponse:
    """Without twitterapi.io, or when it fails, the Community comes back without a name."""
    return await mediator.look_up_community(reader=reader, pasted=lookup_request.pasted)


# Open to Users who aren't Subscribed, so their Published and Failed history stays visible.
@router.get(
    "/scheduled-posts",
    response_model=ScheduledPostsListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_scheduled_posts(
    state: Optional[ScheduledPostState] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> ScheduledPostsListResponse:
    return await mediator.list_scheduled_posts(db=db, user=current_user, state=state)


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
    """With `publish_now`, publishes on X before answering: it comes back Published or Failed."""
    community = create_request.community
    return await mediator.create_scheduled_post(
        db=db,
        publisher=publisher,
        user=current_user,
        text=create_request.text,
        publish_at=create_request.publish_at,
        publish_now=create_request.publish_now,
        source_version_id=create_request.source_version_id,
        community=Community(id=community.id, name=community.name) if community else None,
        share_with_followers=create_request.share_with_followers,
        now=clock(),
    )


@router.patch(
    "/scheduled-posts/{scheduled_post_id}",
    response_model=ScheduledPostResponse,
    status_code=status.HTTP_200_OK,
)
async def edit_scheduled_post(
    scheduled_post_id: str,
    update_request: ScheduledPostUpdateRequest,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> ScheduledPostResponse:
    return await mediator.edit_scheduled_post(
        db=db,
        user=current_user,
        scheduled_post_id=scheduled_post_id,
        text=update_request.text,
        publish_at=update_request.publish_at,
        now=clock(),
    )


@router.delete(
    "/scheduled-posts/{scheduled_post_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_scheduled_post(
    scheduled_post_id: str,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
) -> None:
    await mediator.cancel_scheduled_post(
        db=db, user=current_user, scheduled_post_id=scheduled_post_id
    )
