"""The MCP tools for Scheduled posts, over the same mediator as the router."""

from contextlib import contextmanager
from typing import Iterator, Optional

from fastapi import HTTPException, status

from pumpkit.auth.models import User
from pumpkit.authors.x_reader import get_x_reader
from pumpkit.core.config import settings
from pumpkit.core.mcp_tools import (
    ADDITIVE,
    DESTRUCTIVE,
    READ_ONLY,
    READ_ONLY_RATE,
    McpTool,
    ToolCall,
)
from pumpkit.core.schemas import LinkResponse
from pumpkit.scheduling import mediator
from pumpkit.scheduling.communities import Community, Destination
from pumpkit.scheduling.models import ScheduledPostState
from pumpkit.scheduling.schemas import (
    CommunityLookupRequest,
    PastCommunitiesResponse,
    ScheduledPageMessage,
    ScheduledPostAnswer,
    ScheduledPostCreateRequest,
    ScheduledPostResponse,
    ScheduledPostsListAnswer,
    ScheduledPostUpdateRequest,
)
from pumpkit.x_connection.x_publisher import get_x_publisher


def scheduled_page_url() -> str:
    return f"{settings.frontend_url()}/scheduled"


def _answer(scheduled_post: ScheduledPostResponse) -> ScheduledPostAnswer:
    return ScheduledPostAnswer(
        **scheduled_post.model_dump(), scheduled_page_url=scheduled_page_url()
    )


@contextmanager
def _x_connection_links_to_scheduled_page() -> Iterator[None]:
    """Adds the Scheduled page link to the X connection refusals: connecting X needs a browser."""
    try:
        yield
    except HTTPException as refusal:
        if refusal.detail not in (mediator.CONNECT_X_FIRST, mediator.RECONNECT_X_FIRST):
            raise
        raise HTTPException(
            status_code=refusal.status_code, detail=f"{refusal.detail} {scheduled_page_url()}"
        ) from None


async def _post_text(call: ToolCall[User], text: Optional[str], version_id: Optional[str]) -> str:
    """The text a Scheduled post publishes: typed, or a Version's Final copied."""
    if text is not None and version_id is None:
        return text
    if version_id is not None and text is None:
        return await mediator.version_final(db=call.db, user=call.user, version_id=version_id)
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail="Give either the text or a Version id, not both.",
    )


async def _community(call: ToolCall[User], pasted: str) -> Community:
    """The Community a pasted URL or ID names, looked up on X as the web app does before sending."""
    lookup_request = CommunityLookupRequest(pasted=pasted)
    reader = await call.provide(get_x_reader)
    found = await mediator.look_up_community(reader=reader, pasted=lookup_request.pasted)
    return Community(id=found.id, name=found.name)


async def _destination(
    call: ToolCall[User], community: Optional[str], share_with_followers: bool
) -> Destination:
    return Destination(
        community=await _community(call, community) if community is not None else None,
        share_with_followers=share_with_followers,
    )


async def _create_scheduled_post(
    call: ToolCall[User],
    *,
    text: Optional[str],
    version_id: Optional[str],
    publish_at: Optional[str],
    publish_now: bool,
    community: Optional[str],
    share_with_followers: bool,
) -> ScheduledPostAnswer:
    """A new Scheduled post from typed text or a Version, checked as the create route checks it."""
    create_request = ScheduledPostCreateRequest.model_validate(
        {
            "text": await _post_text(call, text, version_id),
            "publish_at": publish_at,
            "publish_now": publish_now,
            "source_version_id": version_id,
        }
    )
    destination = await _destination(call, community, share_with_followers)
    publisher = await call.provide(get_x_publisher)
    with _x_connection_links_to_scheduled_page():
        scheduled_post = await mediator.create_scheduled_post(
            db=call.db,
            publisher=publisher,
            user=call.user,
            text=create_request.text,
            publish_at=create_request.publish_at,
            publish_now=create_request.publish_now,
            now=call.now,
            source_version_id=create_request.source_version_id,
            destination=destination,
        )
    return _answer(scheduled_post)


async def schedule_post(
    call: ToolCall[User],
    publish_at: str,
    text: Optional[str] = None,
    version_id: Optional[str] = None,
    community: Optional[str] = None,
    share_with_followers: bool = False,
) -> ScheduledPostAnswer:
    """
    Schedule a post on the User's connected X account for `publish_at`, an ISO 8601 time with
    its UTC offset, on a whole minute and at least a minute from now. Give the text, or the id
    of a Version to publish its Final. It goes to the User's profile, or to the Community whose
    URL or ID `community` holds, where `share_with_followers` also shows it to their followers.
    """
    return await _create_scheduled_post(
        call,
        text=text,
        version_id=version_id,
        publish_at=publish_at,
        publish_now=False,
        community=community,
        share_with_followers=share_with_followers,
    )


async def list_scheduled_posts(
    call: ToolCall[User], state: Optional[ScheduledPostState] = None
) -> ScheduledPostsListAnswer:
    """
    List the User's Scheduled posts with their state, publish time and Community: waiting ones
    soonest first, then Published and Failed ones newest first. A Failed one says why it
    failed, and a Published one links to the post on X.
    """
    listed = await mediator.list_scheduled_posts(db=call.db, user=call.user, state=state)
    return ScheduledPostsListAnswer(data=listed.data, scheduled_page_url=scheduled_page_url())


async def list_past_communities(call: ToolCall[User]) -> PastCommunitiesResponse:
    """
    List the Communities the User posted to before from the connected X account, most recently
    used first, to offer them for a Scheduled post.
    """
    return await mediator.list_past_communities(db=call.db, user=call.user)


async def edit_scheduled_post(
    call: ToolCall[User],
    scheduled_post_id: str,
    text: Optional[str] = None,
    publish_at: Optional[str] = None,
    community: Optional[str] = None,
    to_profile: bool = False,
    share_with_followers: Optional[bool] = None,
) -> ScheduledPostAnswer:
    """
    Change a waiting or Failed Scheduled post: its text, its publish time (an ISO 8601 time
    with its UTC offset, which gives a Failed one another try), the Community whose URL or ID
    `community` holds, or, with `to_profile`, send it to the User's profile instead. Leave out
    what stays the same.
    """
    if community is not None and to_profile:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Give either a Community or the profile, not both.",
        )
    changes: dict[str, object] = {
        name: value
        for name, value in (
            ("text", text),
            ("publish_at", publish_at),
            ("share_with_followers", share_with_followers),
        )
        if value is not None
    }
    new_community = await _community(call, community) if community is not None else None
    if new_community is not None:
        changes["community"] = {"id": new_community.id, "name": new_community.name}
    elif to_profile:
        changes["community"] = None
    update_request = ScheduledPostUpdateRequest.model_validate(changes)
    with _x_connection_links_to_scheduled_page():
        scheduled_post = await mediator.edit_scheduled_post(
            db=call.db,
            user=call.user,
            scheduled_post_id=scheduled_post_id,
            text=update_request.text,
            publish_at=update_request.publish_at,
            changes_community=update_request.changes_community,
            community=new_community,
            share_with_followers=update_request.share_with_followers,
            now=call.now,
        )
    return _answer(scheduled_post)


async def delete_scheduled_post(
    call: ToolCall[User], scheduled_post_id: str
) -> ScheduledPageMessage:
    """Delete a waiting or Failed Scheduled post, so it is never published. It can't be undone."""
    await mediator.cancel_scheduled_post(
        db=call.db, user=call.user, scheduled_post_id=scheduled_post_id
    )
    return ScheduledPageMessage(
        message="The Scheduled post is deleted.", scheduled_page_url=scheduled_page_url()
    )


async def connect_x(call: ToolCall[User]) -> LinkResponse:
    """
    Where the User connects, reconnects or disconnects their X account: the Scheduled page of
    the Pumpkit web app, since X asks them to sign in and approve in a browser.
    """
    url = scheduled_page_url()
    return LinkResponse(
        message=f"Connect, reconnect or disconnect your X account on the Scheduled page: {url}",
        url=url,
    )


TOOLS = [
    # The rate of `POST /scheduled-posts`.
    McpTool(schedule_post, rate="10/minute", annotations=ADDITIVE),
    McpTool(list_scheduled_posts, rate=READ_ONLY_RATE, annotations=READ_ONLY),
    # The web edit and delete routes have no limit; these take the create route's.
    McpTool(edit_scheduled_post, rate="10/minute", annotations=ADDITIVE),
    McpTool(delete_scheduled_post, rate="10/minute", annotations=DESTRUCTIVE),
    McpTool(list_past_communities, rate=READ_ONLY_RATE, annotations=READ_ONLY),
    McpTool(connect_x, rate=READ_ONLY_RATE, annotations=READ_ONLY, needs_access=False),
]
