"""The MCP tools for Scheduled posts, over the same mediator as the router."""

from typing import Optional

from fastapi import HTTPException, status

from pumpkit.auth.models import User
from pumpkit.core.config import settings
from pumpkit.core.mcp_tools import ADDITIVE, READ_ONLY, READ_ONLY_RATE, McpTool, ToolCall
from pumpkit.scheduling import mediator
from pumpkit.scheduling.models import ScheduledPostState
from pumpkit.scheduling.schemas import (
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


async def schedule_post(
    call: ToolCall[User],
    publish_at: str,
    text: Optional[str] = None,
    version_id: Optional[str] = None,
) -> ScheduledPostAnswer:
    """
    Schedule a post on the User's connected X account for `publish_at`, an ISO 8601 time with
    its UTC offset, on a whole minute and at least a minute from now. Give the text, or the id
    of a Version to publish its Final.
    """
    create_request = ScheduledPostCreateRequest.model_validate(
        {
            "text": await _post_text(call, text, version_id),
            "publish_at": publish_at,
            "source_version_id": version_id,
        }
    )
    publisher = await call.provide(get_x_publisher)
    scheduled_post = await mediator.create_scheduled_post(
        db=call.db,
        publisher=publisher,
        user=call.user,
        text=create_request.text,
        publish_at=create_request.publish_at,
        publish_now=False,
        now=call.now,
        source_version_id=create_request.source_version_id,
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
