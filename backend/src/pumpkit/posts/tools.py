"""The MCP tools for writing Posts, over the same mediator as the router."""

from pumpkit.auth.models import User
from pumpkit.core.llm import get_llm
from pumpkit.core.mcp_tools import ADDITIVE, McpTool, ToolCall
from pumpkit.posts import mediator
from pumpkit.posts.formats import FORMAT_POST, Format
from pumpkit.posts.schemas import WRITE_RATE, PostResponse, PostStartRequest


async def start_post(
    call: ToolCall[User], brief: str, format: Format = FORMAT_POST
) -> PostResponse:
    """
    Start a post from a brief, what the post is about and what the user thinks about it. Pumpkit
    plans the post around the user's positioning, then writes its first version from that plan.
    It is refused until the user has a positioning, which `set_positioning` saves. A thread is
    written in the style of the user's inspiration authors, so it is also refused until one of
    them has posts. `plan` says what the post is built for: its core idea, the
    takeaway, the funnel stage (`top` for reach, `middle` for trust, `bottom` for conversion),
    the desired action and the length. `format` is "post"
    for a single X post, the default, or "thread" for a thread: several parts, each one X post
    that replies to the one before, as many as the brief needs. Show the user the version's
    text, meant for X, with every part and its character count. Takes a few minutes.
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
