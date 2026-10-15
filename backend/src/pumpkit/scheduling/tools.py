"""The MCP tools for Scheduled posts, over the same mediator as the router."""

from contextlib import contextmanager
from typing import Iterator, Optional

from fastapi import HTTPException, status

from pumpkit.auth.models import User
from pumpkit.authors.x_reader import get_x_reader
from pumpkit.core.config import settings
from pumpkit.core.mcp_tools import ADDITIVE, READ_ONLY, READ_ONLY_RATE, McpTool, ToolCall
from pumpkit.scheduling import mediator
from pumpkit.scheduling.communities import Community, Destination
from pumpkit.scheduling.models import ScheduledPostState
from pumpkit.scheduling.schemas import (
    CommunityLookupRequest,
    ScheduledPostAnswer,
    ScheduledPostCreateRequest,
    ScheduledPostResponse,
    ScheduledPostsListAnswer,
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
    if (text is None) == (version_id is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Give either the text or a Version id, not both.",
        )
    if version_id is not None:
        return await mediator.version_final(db=call.db, user=call.user, version_id=version_id)
    assert text is not None
    return text


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
    create_request = ScheduledPostCreateRequest.model_validate(
        {
            "text": await _post_text(call, text, version_id),
            "publish_at": publish_at,
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
            publish_now=False,
            now=call.now,
            source_version_id=create_request.source_version_id,
            destination=destination,
        )
    return _answer(scheduled_post)


async def list_scheduled_posts(
    call: ToolCall[User], state: Optional[ScheduledPostState] = None
) -> ScheduledPostsListAnswer:
    """
    List the User's Scheduled posts, soonest first, with their state, publish time and
    Community. A Failed one says why it failed; a Published one links to the post on X.
    """
    listed = await mediator.list_scheduled_posts(db=call.db, user=call.user, state=state)
    return ScheduledPostsListAnswer(data=listed.data, scheduled_page_url=scheduled_page_url())


TOOLS = [
    # The rate of `POST /scheduled-posts`.
    McpTool(schedule_post, rate="10/minute", annotations=ADDITIVE),
    McpTool(list_scheduled_posts, rate=READ_ONLY_RATE, annotations=READ_ONLY),
]
