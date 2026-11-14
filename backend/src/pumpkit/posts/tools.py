"""The MCP tools for writing Posts, over the same mediator as the router."""

from pumpkit.auth.models import User
from pumpkit.core.background import get_background_tasks
from pumpkit.core.db.session import get_session_maker
from pumpkit.core.llm import get_llm
from pumpkit.core.mcp_tools import ADDITIVE, McpTool, ToolCall
from pumpkit.core.time import get_clock
from pumpkit.posts import mediator
from pumpkit.posts.schemas import WRITE_RATE, BriefRequest, PostResponse


async def start_post(call: ToolCall[User], brief: str) -> PostResponse:
    """
    Start a post from a brief, what the post is about and what the user thinks about it. Pumpkit
    plans the post around the user's positioning, then writes its first version from that plan.
    When the brief holds several separate ideas, Pumpkit still writes one post covering all of
    them; the web app's New post can write one post per idea instead. It is refused until the
    user has a positioning, which `set_positioning` saves. `plan` says
    what the post is built for: its core idea, the takeaway, the funnel stage (`top` for reach,
    `middle` for trust, `bottom` for conversion), the desired action, the format and the length.
    The format is "post" for a single X post or "thread" for a thread: several parts, each one
    X post that replies to the one before. Pumpkit chooses a thread when the material needs more
    room than one post on the user's account holds, or when the brief asks for one ("as a
    thread"); a thread has no length. It answers once the post is planned, with `writing_state`
    "writing" and no version yet: Pumpkit writes the first version in the background, which takes
    about a minute. Read the post with `get_post` until `writing_state` is null, then show the
    user the text, meant for X, with every part and its character count. "not_written" means
    Pumpkit couldn't write it; the user can retry from the post's page in the web app.
    """
    start_request = BriefRequest(brief=brief)
    return await mediator.start_post(
        db=call.db,
        llm=await call.provide(get_llm),
        tasks=await call.provide(get_background_tasks),
        sessions=await call.provide(get_session_maker),
        user=call.user,
        brief=start_request.brief,
        clock=await call.provide(get_clock),
    )


TOOLS = [
    McpTool(start_post, rate=WRITE_RATE, annotations=ADDITIVE),
]
