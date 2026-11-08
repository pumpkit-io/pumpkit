from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Path, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.authors.x_reader import XReader, get_x_reader
from pumpkit.billing.dependencies import require_subscribed_user
from pumpkit.core.db.session import get_async_db
from pumpkit.core.rate_limit import limiter
from pumpkit.core.storage import FileStorage, get_file_storage
from pumpkit.core.time import Clock, get_clock
from pumpkit.posts.llm import LLM, get_llm
from pumpkit.posts.media_upload import ReceivedMedia, receive_media
from pumpkit.posts.schemas import WRITE_RATE as VERSION_WRITE_RATE
from pumpkit.posts.schemas import AltTextRequest, MediaResponse, TextResponse, VersionResponse
from pumpkit.scheduling import mediator
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
    FeedbackRequest,
    PastCommunitiesResponse,
    PostDetailResponse,
    PostsPageRequest,
    PostsPageResponse,
    ScheduledPostCreateRequest,
    ScheduledPostResponse,
    ScheduledPostUpdateRequest,
    TextEditRequest,
    UploadedMediaResponse,
    UsageResponse,
    XConnectionResponse,
)
from pumpkit.x_connection.schemas import XAuthorizationCompleteRequest
from pumpkit.x_connection.x_publisher import XPublisher, get_x_publisher

router = APIRouter(tags=["scheduled-posts"])
# Served here, not from posts: a Post's status, and so whether it takes Feedback, comes from
# its Scheduled post.
posts_router = APIRouter(tags=["posts"])
# The X connection routes that answer with the Scheduled posts waiting. Two routers, so main.py
# can mount them around x_connection's router and keep the OpenAPI document's order.
x_connection_router = APIRouter(tags=["x-connection"])
x_authorization_router = APIRouter(tags=["x-connection"])
# Served here, not from billing: scheduling and posts count the usage, and billing sits below them.
usage_router = APIRouter(tags=["usage"])


@usage_router.get("/usage", response_model=UsageResponse, status_code=status.HTTP_200_OK)
async def get_usage(
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
    at: Annotated[
        Optional[datetime],
        Query(description="A moment whose Allowance period to report, such as a publish time."),
    ] = None,
) -> UsageResponse:
    return await mediator.get_usage(db=db, user=current_user, at=at or clock(), now=clock())


@x_connection_router.get(
    "/x-connection", response_model=XConnectionResponse, status_code=status.HTTP_200_OK
)
async def get_x_connection(
    current_user: User = Depends(require_subscribed_user),
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


@router.get(
    "/scheduled-posts/communities",
    response_model=PastCommunitiesResponse,
    status_code=status.HTTP_200_OK,
)
async def list_past_communities(
    current_user: User = Depends(require_subscribed_user),
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
    storage: FileStorage = Depends(get_file_storage),
    reader: XReader = Depends(get_x_reader),
    clock: Clock = Depends(get_clock),
) -> ScheduledPostResponse:
    """
    With `publish_now`, publishes on X before answering: it comes back Published or Failed. With
    a GIF or a video it comes back scheduled and `posting`, due now, for the publisher.
    """
    new = NewScheduledPost(
        post_id=create_request.post_id,
        publish_at=create_request.publish_at,
        publish_now=create_request.publish_now,
        community=create_request.community,
        share_with_followers=create_request.share_with_followers,
    )
    return await mediator.create_scheduled_post(
        db=db,
        publisher=publisher,
        storage=storage,
        reader=reader,
        user=current_user,
        new=new,
        clock=clock,
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
    publisher: XPublisher = Depends(get_x_publisher),
    storage: FileStorage = Depends(get_file_storage),
    reader: XReader = Depends(get_x_reader),
    clock: Clock = Depends(get_clock),
) -> ScheduledPostResponse:
    """With `publish_now`, publishes on X before answering, as creating one does."""
    edit = ScheduledPostEdit(
        parts=update_request.parts,
        copy_text=update_request.copy_text,
        publish_at=update_request.publish_at,
        publish_now=update_request.publish_now,
        destination=_destination_change(update_request),
        share_with_followers=update_request.share_with_followers,
    )
    return await mediator.edit_scheduled_post(
        db=db,
        publisher=publisher,
        storage=storage,
        reader=reader,
        user=current_user,
        scheduled_post_id=scheduled_post_id,
        edit=edit,
        clock=clock,
    )


@router.delete(
    "/scheduled-posts/{scheduled_post_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_scheduled_post(
    scheduled_post_id: str,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> None:
    await mediator.cancel_scheduled_post(
        db=db, user=current_user, scheduled_post_id=scheduled_post_id, now=clock()
    )


async def _uploading_user(
    current_user: User = Depends(require_subscribed_user), db: AsyncSession = Depends(get_async_db)
) -> User:
    await mediator.start_media_upload(db=db, user=current_user)
    return current_user


@router.post(
    "/scheduled-posts/{scheduled_post_id}/parts/{part_number}/media",
    response_model=MediaResponse,
    status_code=status.HTTP_201_CREATED,
)
async def attach_scheduled_post_media(
    scheduled_post_id: str,
    part_number: Annotated[int, Path(ge=1)],
    # Resolved in this order, so the User is counted and the connection freed before the body.
    current_user: User = Depends(_uploading_user),
    received: ReceivedMedia = Depends(receive_media),
    db: AsyncSession = Depends(get_async_db),
    storage: FileStorage = Depends(get_file_storage),
    clock: Clock = Depends(get_clock),
) -> MediaResponse:
    """
    Attaches an image, a GIF or a video, sent as `attach_text_media` takes it, to Part
    `part_number` (from 1) of a scheduled or Failed Scheduled post, after the Part's other Media.
    Only the Scheduled post's own copy changes, not the Post's Text. A Part already on X is
    refused, and so is a Scheduled post publishing or Published.
    """
    return await mediator.attach_scheduled_post_media(
        db=db,
        storage=storage,
        user=current_user,
        scheduled_post_id=scheduled_post_id,
        part_number=part_number,
        received=received,
        now=clock(),
    )


@router.delete(
    "/scheduled-posts/{scheduled_post_id}/media/{media_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_scheduled_post_media(
    scheduled_post_id: str,
    media_id: str,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> None:
    """
    Takes the Media off a scheduled or Failed Scheduled post's own copy; the Post's Text keeps its
    own. A Part already on X is refused, and so is a Scheduled post publishing or Published.
    """
    await mediator.remove_scheduled_post_media(
        db=db,
        user=current_user,
        scheduled_post_id=scheduled_post_id,
        media_id=media_id,
        now=clock(),
    )


@router.put(
    "/scheduled-posts/{scheduled_post_id}/media/{media_id}/alt-text", response_model=MediaResponse
)
async def set_scheduled_post_media_alt_text(
    scheduled_post_id: str,
    media_id: str,
    alt_text_request: AltTextRequest,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> MediaResponse:
    """
    Sets the alt text of an image or GIF on a waiting Scheduled post, up to 1,000 characters; empty
    or null clears it. A Part already on X is refused, and so is a Failed, publishing or Published
    Scheduled post: a Failed Post's alt text changes on its Text.
    """
    return await mediator.set_scheduled_post_media_alt_text(
        db=db,
        user=current_user,
        scheduled_post_id=scheduled_post_id,
        media_id=media_id,
        alt_text=alt_text_request.alt_text,
        now=clock(),
    )


@posts_router.get("/posts", response_model=PostsPageResponse, status_code=status.HTTP_200_OK)
async def list_posts(
    page: Annotated[PostsPageRequest, Query()],
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> PostsPageResponse:
    return await mediator.list_posts(
        db=db,
        user=current_user,
        status=page.status,
        limit=page.limit,
        offset=page.offset,
        now=clock(),
    )


@posts_router.get(
    "/posts/{post_id}", response_model=PostDetailResponse, status_code=status.HTTP_200_OK
)
async def get_post(
    post_id: str,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> PostDetailResponse:
    return await mediator.get_post(db=db, user=current_user, post_id=post_id, now=clock())


@posts_router.post(
    "/posts/{post_id}/versions",
    response_model=VersionResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(VERSION_WRITE_RATE)
async def give_feedback(
    request: Request,
    post_id: str,
    feedback_request: FeedbackRequest,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    llm: LLM = Depends(get_llm),
    clock: Clock = Depends(get_clock),
) -> VersionResponse:
    """
    Writes the Version before answering, which takes two model calls. A Scheduled or Published
    Post is refused.
    """
    return await mediator.give_feedback(
        db=db,
        llm=llm,
        user=current_user,
        post_id=post_id,
        feedback=feedback_request.feedback,
        format=feedback_request.format,
        now=clock(),
        sent_text=feedback_request.text,
    )


@posts_router.post(
    "/posts/{post_id}/versions/{version_number}/restore",
    response_model=TextResponse,
    status_code=status.HTTP_200_OK,
)
async def restore_version(
    post_id: str,
    version_number: int,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> TextResponse:
    """
    Makes the Version the Post's Text without writing a new one. A Scheduled or Published Post
    is refused.
    """
    return await mediator.restore_version(
        db=db, user=current_user, post_id=post_id, version_number=version_number, now=clock()
    )


@posts_router.put(
    "/posts/{post_id}/text", response_model=TextResponse, status_code=status.HTTP_200_OK
)
async def edit_text(
    post_id: str,
    edit_request: TextEditRequest,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> TextResponse:
    """
    Saves the User's edit of the Post's Text, every Part in order. Idempotent, so the web app
    retries a failed save as it is. A Scheduled or Published Post is refused.
    """
    return await mediator.edit_text(
        db=db, user=current_user, post_id=post_id, parts=edit_request.parts, now=clock()
    )


@posts_router.post(
    "/posts/{post_id}/text/parts/{part_number}/media",
    response_model=MediaResponse,
    status_code=status.HTTP_201_CREATED,
)
async def attach_text_media(
    post_id: str,
    part_number: Annotated[int, Path(ge=1)],
    # Resolved in this order, so the User is counted and the connection freed before the body.
    current_user: User = Depends(_uploading_user),
    received: ReceivedMedia = Depends(receive_media),
    db: AsyncSession = Depends(get_async_db),
    storage: FileStorage = Depends(get_file_storage),
    clock: Clock = Depends(get_clock),
) -> MediaResponse:
    """
    Attaches an image, a GIF or a video, sent as the multipart field `file`, to Part `part_number`
    (from 1) of the Post's Text, after the Part's other Media. A video may come with the browser's
    `duration_ms` and its first frame as the image `poster`. The type is read from the file's
    bytes, and an upload larger than X takes of its kind is refused while it streams. A Scheduled
    or Published Post is refused.
    """
    return await mediator.attach_text_media(
        db=db,
        storage=storage,
        user=current_user,
        post_id=post_id,
        part_number=part_number,
        received=received,
        now=clock(),
    )


async def _link_upload(
    token: str, db: AsyncSession = Depends(get_async_db), clock: Clock = Depends(get_clock)
) -> mediator.LinkUpload:
    return await mediator.start_link_upload(db=db, token=token, now=clock())


@posts_router.post(
    f"{mediator.UPLOAD_LINKS_PATH}/{{token}}",
    response_model=UploadedMediaResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_through_link(
    # Resolved in this order, so the link is spent and the connection freed before the body.
    upload: mediator.LinkUpload = Depends(_link_upload),
    received: ReceivedMedia = Depends(receive_media),
    db: AsyncSession = Depends(get_async_db),
    storage: FileStorage = Depends(get_file_storage),
    clock: Clock = Depends(get_clock),
) -> UploadedMediaResponse:
    """
    Attaches an image, a GIF or a video, sent as the multipart field `file`, through a one-time
    link `attach_media` made: to the Part it names, of the Post's Text or its waiting Scheduled
    post's copy. The link is the only credential, and the first upload through it spends it.
    """
    return await mediator.attach_through_link(
        db=db, storage=storage, upload=upload, received=received, now=clock()
    )


@posts_router.delete(
    "/posts/{post_id}/text/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_text_media(
    post_id: str,
    media_id: str,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
) -> None:
    """Takes the Media off the Post's Text. A Scheduled or Published Post is refused."""
    await mediator.remove_text_media(db=db, user=current_user, post_id=post_id, media_id=media_id)


@posts_router.put("/posts/{post_id}/text/media/{media_id}/alt-text", response_model=MediaResponse)
async def set_text_media_alt_text(
    post_id: str,
    media_id: str,
    alt_text_request: AltTextRequest,
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
) -> MediaResponse:
    """
    Sets the alt text of an image or GIF on the Post's Text, up to 1,000 characters; empty or null
    clears it. A Scheduled or Published Post is refused, and so is a Part already on X.
    """
    return await mediator.set_text_media_alt_text(
        db=db,
        user=current_user,
        post_id=post_id,
        media_id=media_id,
        alt_text=alt_text_request.alt_text,
    )
