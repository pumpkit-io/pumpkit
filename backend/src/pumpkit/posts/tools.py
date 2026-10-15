"""The MCP tools for writing Posts, over the same mediator as the router."""

from pumpkit.auth.models import User
from pumpkit.core.mcp_tools import ADDITIVE, READ_ONLY, READ_ONLY_RATE, McpTool, ToolCall
from pumpkit.posts import mediator
from pumpkit.posts.llm import get_llm
from pumpkit.posts.schemas import (
    FeedbackRequest,
    PostResponse,
    PostStartRequest,
    PostToolResponse,
    VersionToolResponse,
)


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


async def give_feedback(call: ToolCall[User], post_id: str, feedback: str) -> VersionToolResponse:
    """
    Give Feedback in plain words on the latest Version of one of the User's Posts, such as
    "shorter" or "end with a question", and write its next Version, keeping the earlier ones.
    Show the User the new Final and its character count. Takes up to a minute.
    """
    feedback_request = FeedbackRequest(feedback=feedback)
    llm = await call.provide(get_llm)
    version = await mediator.add_version(
        db=call.db,
        llm=llm,
        user=call.user,
        post_id=post_id,
        feedback=feedback_request.feedback,
        now=call.now,
    )
    return VersionToolResponse.model_validate(version.model_dump())


async def get_post(call: ToolCall[User], post_id: str) -> PostToolResponse:
    """
    Read one of the User's Posts: its Brief and every Version in order, each with the Feedback
    that made it, its Final and the Final's character count. A Version's id can be scheduled.
    """
    return _post_answer(await mediator.get_post(db=call.db, user=call.user, post_id=post_id))


TOOLS = [
    # The rates of `POST /posts` and `POST /posts/{post_id}/versions`.
    McpTool(start_post, rate="20/minute", annotations=ADDITIVE),
    McpTool(give_feedback, rate="20/minute", annotations=ADDITIVE),
    McpTool(get_post, rate=READ_ONLY_RATE, annotations=READ_ONLY),
]
