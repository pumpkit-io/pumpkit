"""The MCP tools for a User's Inspiration authors, over the same mediator as the router."""

from pumpkit.auth.models import User
from pumpkit.authors import mediator
from pumpkit.authors.handles import normalize_handle
from pumpkit.authors.schemas import (
    WRITE_RATE,
    InspirationAuthorAddRequest,
    InspirationAuthorResponse,
    InspirationAuthorsListToolResponse,
    InspirationAuthorToolResponse,
)
from pumpkit.authors.x_reader import get_x_reader
from pumpkit.core.mcp_tools import (
    ADDITIVE,
    DESTRUCTIVE,
    READ_ONLY,
    READ_ONLY_RATE,
    McpTool,
    ToolCall,
)
from pumpkit.core.schemas import MessageResponse


def _tool_response(author: InspirationAuthorResponse) -> InspirationAuthorToolResponse:
    return InspirationAuthorToolResponse(
        handle=author.handle, last_fetched_at=author.last_fetched_at, post_count=author.post_count
    )


async def list_inspiration_authors(call: ToolCall[User]) -> InspirationAuthorsListToolResponse:
    """
    List the User's Inspiration authors, the X accounts whose posts set the style of every Post
    Pumpkit writes for them, in the order they were added, with how many posts each has stored.
    """
    listed = await mediator.list_authors(db=call.db, user=call.user)
    return InspirationAuthorsListToolResponse(
        data=[_tool_response(author) for author in listed.data]
    )


async def add_inspiration_author(
    call: ToolCall[User], handle: str
) -> InspirationAuthorToolResponse:
    """
    Add an X account as an Inspiration author, by its handle with or without the @. Pumpkit
    reads its recent original posts at once. A User has up to three Inspiration authors.
    """
    add_request = InspirationAuthorAddRequest(handle=handle)
    reader = await call.provide(get_x_reader)
    added = await mediator.add_author(
        db=call.db, reader=reader, user=call.user, handle=add_request.handle, now=call.now
    )
    return _tool_response(added)


async def remove_inspiration_author(call: ToolCall[User], handle: str) -> MessageResponse:
    """Remove one of the User's Inspiration authors, by its handle with or without the @."""
    await mediator.remove_author(db=call.db, user=call.user, handle=handle)
    return MessageResponse(
        message=f"@{normalize_handle(handle)} is no longer one of your Inspiration authors."
    )


TOOLS = [
    McpTool(list_inspiration_authors, rate=READ_ONLY_RATE, annotations=READ_ONLY),
    McpTool(add_inspiration_author, rate=WRITE_RATE, annotations=ADDITIVE),
    McpTool(remove_inspiration_author, rate=WRITE_RATE, annotations=DESTRUCTIVE),
]
