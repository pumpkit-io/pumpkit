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
from pumpkit.scheduling.models import ScheduledPostState
from pumpkit.scheduling.rules import (
    DestinationChange,
    KeepDestination,
    NewScheduledPost,
    ScheduledPostEdit,
    ToCommunity,
    ToProfile,
)
from pumpkit.scheduling.schemas import (
    WRITE_RATE,
    CommunityLookupRequest,
    CommunityResponse,
    PastCommunitiesResponse,
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


@router.get(
    "/scheduled-posts/communities",
    response_model=PastCommunitiesResponse,
    status_code=status.HTTP_200_OK,
)
async def list_past_communities(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> PastCommunitiesResponse:
    return await mediator.list_past_communities(db=db, user=current_user)


@router.post(
    "/scheduled-posts",
    response_model=ScheduledPostResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(WRITE_RATE)
async def create_scheduled_post(
    request: Request,
    create_request: ScheduledPostCreateRequest,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    publisher: XPublisher = Depends(get_x_publisher),
    reader: XReader = Depends(get_x_reader),
    clock: Clock = Depends(get_clock),
) -> ScheduledPostResponse:
    """With `publish_now`, publishes on X before answering: it comes back Published or Failed."""
    new = NewScheduledPost(
        parts=create_request.parts,
        version_id=create_request.source_version_id,
        publish_at=create_request.publish_at,
        publish_now=create_request.publish_now,
        community=create_request.community,
        share_with_followers=create_request.share_with_followers,
    )
    return await mediator.create_scheduled_post(
        db=db, publisher=publisher, reader=reader, user=current_user, new=new, now=clock()
    )


def _destination_change(update_request: ScheduledPostUpdateRequest) -> DestinationChange:
    """Absent keeps the Destination, null moves to the profile, and a string to that Community."""
    if "community" not in update_request.model_fields_set:
        return KeepDestination()
    if update_request.community is None:
        return ToProfile()
    return ToCommunity(pasted=update_request.community)


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
    reader: XReader = Depends(get_x_reader),
    clock: Clock = Depends(get_clock),
) -> ScheduledPostResponse:
    edit = ScheduledPostEdit(
        parts=update_request.parts,
        publish_at=update_request.publish_at,
        destination=_destination_change(update_request),
        share_with_followers=update_request.share_with_followers,
    )
    return await mediator.edit_scheduled_post(
        db=db,
        reader=reader,
        user=current_user,
        scheduled_post_id=scheduled_post_id,
        edit=edit,
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
