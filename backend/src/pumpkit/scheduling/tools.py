"""The MCP tools for Scheduled posts, over the same mediator as the router."""

from typing import Optional

from pumpkit.auth.models import User
from pumpkit.authors.x_reader import get_x_reader
from pumpkit.core.config import settings
from pumpkit.core.errors import RefusedError
from pumpkit.core.mcp_tools import (
    ADDITIVE,
    DESTRUCTIVE,
    READ_ONLY,
    READ_ONLY_RATE,
    McpTool,
    ToolCall,
)
from pumpkit.core.schemas import LinkToolResponse
from pumpkit.scheduling import mediator
from pumpkit.scheduling.models import FAILED, PUBLISHED, ScheduledPostState
from pumpkit.scheduling.publish import RETRY_WINDOW
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
    PastCommunitiesResponse,
    PostNowToolResponse,
    ScheduledPageMessageToolResponse,
    ScheduledPostCreateRequest,
    ScheduledPostResponse,
    ScheduledPostsListToolResponse,
    ScheduledPostToolResponse,
    ScheduledPostUpdateRequest,
)
from pumpkit.x_connection.x_publisher import get_x_publisher


def scheduled_page_url() -> str:
    return f"{settings.frontend_url()}{mediator.SCHEDULED_PAGE}"


def _tool_response(scheduled_post: ScheduledPostResponse) -> ScheduledPostToolResponse:
    return ScheduledPostToolResponse(
        **scheduled_post.model_dump(), scheduled_page_url=scheduled_page_url()
    )


async def _create_scheduled_post(
    call: ToolCall[User],
    *,
    parts: Optional[list[str]],
    version_id: Optional[str],
    publish_at: Optional[str],
    community: Optional[str],
    share_with_followers: bool,
) -> ScheduledPostToolResponse:
    """A new Scheduled post, its arguments checked by the create route's request schema."""
    create_request = ScheduledPostCreateRequest.model_validate(
        {
            "parts": parts,
            "source_version_id": version_id,
            "publish_at": publish_at,
            "publish_now": publish_at is None,
            "community": community,
            "share_with_followers": share_with_followers,
        }
    )
    new = NewScheduledPost(
        parts=create_request.parts,
        version_id=create_request.source_version_id,
        publish_at=create_request.publish_at,
        publish_now=create_request.publish_now,
        community=create_request.community,
        share_with_followers=create_request.share_with_followers,
    )
    scheduled_post = await mediator.create_scheduled_post(
        db=call.db,
        publisher=await call.provide(get_x_publisher),
        reader=await call.provide(get_x_reader),
        user=call.user,
        new=new,
        now=call.now,
    )
    return _tool_response(scheduled_post)


async def schedule_post(
    call: ToolCall[User],
    publish_at: str,
    parts: Optional[list[str]] = None,
    version_id: Optional[str] = None,
    community: Optional[str] = None,
    share_with_followers: bool = False,
) -> ScheduledPostToolResponse:
    """
    Schedule a post on the User's connected X account for `publish_at`, an ISO 8601 time with
    its UTC offset, on a whole minute and at least a minute from now. Give `parts`, its text
    as a list of Parts in order (one Part for a single X post), or the id of a Version to
    publish its Final. It goes to the User's profile, or to the Community whose URL or ID
    `community` holds, where `share_with_followers` also shows it to their followers.
    """
    return await _create_scheduled_post(
        call,
        parts=parts,
        version_id=version_id,
        publish_at=publish_at,
        community=community,
        share_with_followers=share_with_followers,
    )


def _post_now_message(posted: ScheduledPostToolResponse) -> str:
    """The web app's words for how Post now ended."""
    if posted.state == PUBLISHED:
        return f"Published on X: {posted.x_post_url}"
    if posted.state == FAILED:
        return f"Failed. {posted.failed_reason}"
    # Back in scheduled: X never took it, so the publisher retries it.
    minutes = int(RETRY_WINDOW.total_seconds() // 60)
    return f"X was busy. Pumpkit will keep trying for the next {minutes} minutes."


async def post_now(
    call: ToolCall[User],
    parts: Optional[list[str]] = None,
    version_id: Optional[str] = None,
    community: Optional[str] = None,
    share_with_followers: bool = False,
) -> PostNowToolResponse:
    """
    Publish a post on the User's connected X account right away. Show the User the exact text
    and get their yes first. Give `parts`, its text as a list of Parts in order (one Part for a
    single X post), or the id of a Version to publish its Final. It goes to the User's
    profile, or to the Community whose URL or ID `community` holds, where
    `share_with_followers` also shows it to their followers.
    """
    posted = await _create_scheduled_post(
        call,
        parts=parts,
        version_id=version_id,
        publish_at=None,
        community=community,
        share_with_followers=share_with_followers,
    )
    return PostNowToolResponse(**posted.model_dump(), message=_post_now_message(posted))


async def list_scheduled_posts(
    call: ToolCall[User], state: Optional[ScheduledPostState] = None
) -> ScheduledPostsListToolResponse:
    """
    List the User's Scheduled posts with their state, publish time and Community: waiting ones
    soonest first, then Published and Failed ones newest first. A Failed one says why it
    failed, and a Published one links to the post on X.
    """
    listed = await mediator.list_scheduled_posts(db=call.db, user=call.user, state=state)
    return ScheduledPostsListToolResponse(data=listed.data, scheduled_page_url=scheduled_page_url())


async def list_past_communities(call: ToolCall[User]) -> PastCommunitiesResponse:
    """
    List the Communities the User posted to before from the connected X account, most recently
    used first, to offer them for a Scheduled post.
    """
    return await mediator.list_past_communities(db=call.db, user=call.user)


def _destination_change(community: Optional[str], to_profile: bool) -> DestinationChange:
    if community is not None and to_profile:
        raise RefusedError("Give either a Community or the profile, not both.")
    if community is not None:
        return ToCommunity(pasted=community)
    if to_profile:
        return ToProfile()
    return KeepDestination()


async def edit_scheduled_post(
    call: ToolCall[User],
    scheduled_post_id: str,
    parts: Optional[list[str]] = None,
    publish_at: Optional[str] = None,
    community: Optional[str] = None,
    to_profile: bool = False,
    share_with_followers: Optional[bool] = None,
) -> ScheduledPostToolResponse:
    """
    Change a waiting or Failed Scheduled post: its text, as `parts` that replace every Part,
    its publish time (an ISO 8601 time with its UTC offset, which gives a Failed one another
    try), the Community whose URL or ID `community` holds, or, with `to_profile`, send it to
    the User's profile instead. Leave out what stays the same.
    """
    update_request = ScheduledPostUpdateRequest.model_validate(
        {"parts": parts, "publish_at": publish_at, "community": community}
    )
    edit = ScheduledPostEdit(
        parts=update_request.parts,
        publish_at=update_request.publish_at,
        destination=_destination_change(update_request.community, to_profile),
        share_with_followers=share_with_followers,
    )
    scheduled_post = await mediator.edit_scheduled_post(
        db=call.db,
        reader=await call.provide(get_x_reader),
        user=call.user,
        scheduled_post_id=scheduled_post_id,
        edit=edit,
        now=call.now,
    )
    return _tool_response(scheduled_post)


async def delete_scheduled_post(
    call: ToolCall[User], scheduled_post_id: str
) -> ScheduledPageMessageToolResponse:
    """Delete a waiting or Failed Scheduled post, so it is never published. It can't be undone."""
    await mediator.cancel_scheduled_post(
        db=call.db, user=call.user, scheduled_post_id=scheduled_post_id
    )
    return ScheduledPageMessageToolResponse(
        message="The Scheduled post is deleted.", scheduled_page_url=scheduled_page_url()
    )


async def connect_x(call: ToolCall[User]) -> LinkToolResponse:
    """
    Where the User connects, reconnects or disconnects their X account: the Scheduled page of
    the Pumpkit web app, since X asks them to sign in and approve in a browser.
    """
    url = scheduled_page_url()
    return LinkToolResponse(
        message=f"Connect, reconnect or disconnect your X account on the Scheduled page: {url}",
        url=url,
    )


TOOLS = [
    McpTool(schedule_post, rate=WRITE_RATE, annotations=ADDITIVE),
    # Post now goes through the create route on the web.
    McpTool(post_now, rate=WRITE_RATE, annotations=DESTRUCTIVE),
    McpTool(list_scheduled_posts, rate=READ_ONLY_RATE, annotations=READ_ONLY),
    # The web edit and delete routes have no limit; these take the create route's.
    McpTool(edit_scheduled_post, rate=WRITE_RATE, annotations=ADDITIVE),
    McpTool(delete_scheduled_post, rate=WRITE_RATE, annotations=DESTRUCTIVE),
    McpTool(list_past_communities, rate=READ_ONLY_RATE, annotations=READ_ONLY),
    McpTool(connect_x, rate=READ_ONLY_RATE, annotations=READ_ONLY, needs_access=False),
]
