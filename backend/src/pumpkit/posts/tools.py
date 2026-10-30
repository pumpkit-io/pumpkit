"""The MCP tools for writing Posts, over the same mediator as the router."""

from pumpkit.auth.models import User
from pumpkit.core.mcp_tools import ADDITIVE, McpTool, ToolCall
from pumpkit.posts import mediator
from pumpkit.posts.formats import FORMAT_POST, Format
from pumpkit.posts.llm import get_llm
from pumpkit.posts.schemas import WRITE_RATE, PostResponse, PostStartRequest


async def start_post(
    call: ToolCall[User], brief: str, format: Format = FORMAT_POST
) -> PostResponse:
    """
    Start a post from a brief, what the post is about and what the user thinks about it, and
    write its first version in the style of the user's inspiration authors. `format` is "post"
    for a single X post, the default, or "thread" for a thread: several parts, each one X post
    that replies to the one before, as many as the brief needs. Show the user the version's
    text, meant for X, with every part and its character count. Takes up to a minute.
    """
    start_request = PostStartRequest(brief=brief, format=format)
    llm = await call.provide(get_llm)
    return await mediator.start_post(
        db=call.db,
        llm=llm,
        user=call.user,
        brief=start_request.brief,
        format=start_request.format,
        now=call.now,
    )


TOOLS = [
    McpTool(start_post, rate=WRITE_RATE, annotations=ADDITIVE),
]
