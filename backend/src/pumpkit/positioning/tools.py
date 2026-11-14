"""The MCP tools for a User's Positioning, over the same mediator as the router."""

from pumpkit.auth.models import User
from pumpkit.core.mcp_tools import ADDITIVE, READ_ONLY, READ_ONLY_RATE, McpTool, ToolCall
from pumpkit.positioning import mediator
from pumpkit.positioning.schemas import WRITE_RATE, PositioningResponse, PositioningSaveRequest


async def get_positioning(call: ToolCall[User]) -> PositioningResponse:
    """
    Read the user's positioning: a few sentences saying who they are on X, what they post about,
    who they write for, what they post for and what they can point readers to. `text` is null
    until they save one.
    """
    return await mediator.get_positioning(call.db, call.user)


async def set_positioning(call: ToolCall[User], text: str) -> PositioningResponse:
    """
    Save the user's positioning, in place of any they had: a few first-person sentences covering
    who they are on X, what they post about, who they write for, what they post for and what they
    can point readers to. Up to 4,000 characters.
    """
    save_request = PositioningSaveRequest(text=text)
    return await mediator.save_positioning(call.db, call.user, save_request.text, call.now)


TOOLS = [
    McpTool(get_positioning, rate=READ_ONLY_RATE, annotations=READ_ONLY),
    McpTool(set_positioning, rate=WRITE_RATE, annotations=ADDITIVE),
]
