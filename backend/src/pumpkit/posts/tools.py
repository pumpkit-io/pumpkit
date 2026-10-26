"""The MCP tools for writing Posts, over the same mediator as the router."""

from typing import Optional

from pumpkit.auth.models import User
from pumpkit.core.mcp_tools import ADDITIVE, READ_ONLY, READ_ONLY_RATE, McpTool, ToolCall
from pumpkit.posts import mediator
from pumpkit.posts.formats import FORMAT_POST, Format
from pumpkit.posts.llm import get_llm
from pumpkit.posts.schemas import (
    WRITE_RATE,
    FeedbackRequest,
    PostResponse,
    PostsPageRequest,
    PostsPageResponse,
    PostStartRequest,
    PostToolResponse,
    VersionToolResponse,
)


def _post_tool_response(post: PostResponse) -> PostToolResponse:
    return PostToolResponse.model_validate(post.model_dump())


async def start_post(
    call: ToolCall[User], brief: str, format: Format = FORMAT_POST
) -> PostToolResponse:
    """
    Start a Post from a Brief, what the Post is about and what the User thinks about it, and
    write its first Version in the style of the User's Inspiration authors. `format` is "post"
    for a single X post, the default, or "thread" for a Thread: several Parts, each one X post
    that replies to the one before, as many as the Brief needs. Show the User the Final, the
    text meant for X, with every Part and its character count. Takes up to a minute.
    """
    start_request = PostStartRequest(brief=brief, format=format)
    llm = await call.provide(get_llm)
    post = await mediator.start_post(
        db=call.db,
        llm=llm,
        user=call.user,
        brief=start_request.brief,
        format=start_request.format,
        now=call.now,
    )
    return _post_tool_response(post)


async def give_feedback(
    call: ToolCall[User], post_id: str, feedback: str, format: Optional[Format] = None
) -> VersionToolResponse:
    """
    Give Feedback in plain words on the latest Version of one of the User's Posts, such as
    "shorter", "end with a question" or "make Part 3 punchier", and write its next Version,
    keeping the earlier ones. `format` switches the new Version to "post" (a single X post) or
    "thread"; leave it out to keep the latest Version's Format. Show the User the new Final,
    with every Part and its character count. Takes up to a minute.
    """
    feedback_request = FeedbackRequest(feedback=feedback, format=format)
    llm = await call.provide(get_llm)
    version = await mediator.add_version(
        db=call.db,
        llm=llm,
        user=call.user,
        post_id=post_id,
        feedback=feedback_request.feedback,
        format=feedback_request.format,
        now=call.now,
    )
    return VersionToolResponse.model_validate(version.model_dump())


async def list_posts(call: ToolCall[User], limit: int = 20, offset: int = 0) -> PostsPageResponse:
    """
    List the User's Posts, newest first, each with its Brief and how many Versions it has, so
    the User can pick up a Post from an earlier session. Pages hold up to 50; pass the answer's
    `next_offset` as `offset` for the next page.
    """
    page = PostsPageRequest(limit=limit, offset=offset)
    return await mediator.list_posts(
        db=call.db, user=call.user, limit=page.limit, offset=page.offset
    )


async def get_post(call: ToolCall[User], post_id: str) -> PostToolResponse:
    """
    Read one of the User's Posts: its Brief and every Version in order, each with the Feedback
    that made it, its Final and the Final's character count. A Version's id can be scheduled.
    """
    return _post_tool_response(await mediator.get_post(db=call.db, user=call.user, post_id=post_id))


TOOLS = [
    McpTool(start_post, rate=WRITE_RATE, annotations=ADDITIVE),
    McpTool(give_feedback, rate=WRITE_RATE, annotations=ADDITIVE),
    McpTool(list_posts, rate=READ_ONLY_RATE, annotations=READ_ONLY),
    McpTool(get_post, rate=READ_ONLY_RATE, annotations=READ_ONLY),
]
