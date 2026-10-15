"""The MCP tools for writing Posts, over the same mediator as the router."""

from pumpkit.auth.models import User
from pumpkit.core.mcp_tools import ADDITIVE, McpTool, ToolCall
from pumpkit.posts import mediator
from pumpkit.posts.llm import get_llm
from pumpkit.posts.schemas import PostResponse, PostStartRequest, PostToolResponse


def _post_answer(post: PostResponse) -> PostToolResponse:
    return PostToolResponse.model_validate(post.model_dump())


async def start_post(call: ToolCall[User], brief: str) -> PostToolResponse:
    """
    Start a Post from a Brief, what the Post is about and what the User thinks about it, and
    write its first Version in the style of the User's Inspiration authors. Show the User the
    Final, the text meant for X, and its character count. Takes up to a minute.
    """
    start_request = PostStartRequest(brief=brief)
    llm = await call.provide(get_llm)
    post = await mediator.start_post(
        db=call.db, llm=llm, user=call.user, brief=start_request.brief, now=call.now
    )
    return _post_answer(post)


TOOLS = [
    # The rate of `POST /posts`.
    McpTool(start_post, rate="20/minute", annotations=ADDITIVE),
]
