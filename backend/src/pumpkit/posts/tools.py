"""The MCP tools for writing Posts, over the same mediator as the router."""

from pumpkit.auth.models import User
from pumpkit.core.llm import get_llm
from pumpkit.core.mcp_tools import ADDITIVE, McpTool, ToolCall
from pumpkit.posts import mediator
from pumpkit.posts.schemas import WRITE_RATE, PostResponse, PostStartRequest


async def start_post(call: ToolCall[User], brief: str) -> PostResponse:
    """
    Start a post from a brief, what the post is about and what the user thinks about it. Pumpkit
    plans the post around the user's positioning, then writes its first version from that plan.
    It is refused until the user has a positioning, which `set_positioning` saves. `plan` says
    what the post is built for: its core idea, the takeaway, the funnel stage (`top` for reach,
    `middle` for trust, `bottom` for conversion), the desired action, the format and the length.
    The format is "post" for a single X post or "thread" for a thread: several parts, each one
    X post that replies to the one before. Pumpkit chooses a thread when the material needs more
    room than one post on the user's account holds, or when the brief asks for one ("as a
    thread"); a thread has no length. Show the user the version's text, meant for X, with every
    part and its character count. Takes a few minutes.
    """
    start_request = PostStartRequest(brief=brief)
    llm = await call.provide(get_llm)
    return await mediator.start_post(
        db=call.db,
        llm=llm,
        user=call.user,
        brief=start_request.brief,
        now=call.now,
    )


TOOLS = [
    McpTool(start_post, rate=WRITE_RATE, annotations=ADDITIVE),
]
