"""The MCP tools for planning a Brief and writing its Ideas, over the same mediator as the router."""

from pumpkit.auth.models import User
from pumpkit.core.background import get_background_tasks
from pumpkit.core.db.session import get_session_maker
from pumpkit.core.llm import get_llm
from pumpkit.core.mcp_tools import ADDITIVE, McpTool, ToolCall
from pumpkit.core.time import get_clock
from pumpkit.posts import mediator
from pumpkit.posts.schemas import (
    WRITE_RATE,
    BriefRequest,
    PlannedBriefToolResponse,
    PlannedIdeaToolResponse,
    StartedPostsToolResponse,
    StartedPostToolResponse,
    WriteIdeasRequest,
)


async def plan_posts(call: ToolCall[User], brief: str) -> PlannedBriefToolResponse:
    """
    Plan the posts a brief holds, around the user's positioning, and write none of them. A brief
    is what the user wants to post about and what they think about it. `ideas` are the separate
    posts Pumpkit found in it, in posting order, empty when the brief holds one idea, and
    `single_post` is one post covering the whole brief. Each comes with its plan: its core idea,
    the takeaway, the funnel stage (`top` for reach, `middle` for trust, `bottom` for conversion),
    the desired action, the format ("post" for a single X post, "thread" for several parts, each
    replying to the one before) and, for a single post, the length. Show the user the core idea
    of each, then ask which to write: any of `ideas`, or `single_post` alone. Planning uses no
    generation, but a user can plan 20 briefs an hour. `generations_left` is how many posts the
    user can still have written, null with no cap. Refused until the user has a positioning,
    which `set_positioning` saves, and while the user is at the hourly limit on writing attempts,
    as `write_posts` would be.
    """
    plan_request = BriefRequest(brief=brief)
    planned = await mediator.plan_posts(
        db=call.db,
        llm=await call.provide(get_llm),
        user=call.user,
        brief=plan_request.brief,
        clock=await call.provide(get_clock),
    )
    single, *split = planned.ideas
    return PlannedBriefToolResponse(
        brief_id=planned.id,
        ideas=[
            PlannedIdeaToolResponse.model_validate(idea, from_attributes=True) for idea in split
        ],
        single_post=PlannedIdeaToolResponse.model_validate(single, from_attributes=True),
        generations_left=planned.generations_left,
    )


async def write_posts(
    call: ToolCall[User], brief_id: str, idea_ids: list[str]
) -> StartedPostsToolResponse:
    """
    Start writing a post of each idea `plan_posts` gave for the brief, by the ids in `idea_ids`:
    any of its `ideas`, or its `single_post` alone, never both, not even in two calls, since that
    would post the whole brief and a part of it. The posts are written in parallel in the background, which takes about
    a minute. It answers with each post's id: read each one with `get_post` until `writing_state`
    is null, then show the user its text, meant for X, with every part and its character count.
    "not_written" means Pumpkit couldn't write it, and the user can retry from the post's page in
    the web app. Each post written uses one generation, and none when the writing fails. It writes
    none of them when the user hasn't enough generations or hourly attempts left for all, or when
    one of them is already written.
    """
    write_request = WriteIdeasRequest(idea_ids=idea_ids)
    brief = await mediator.write_ideas(
        db=call.db,
        llm=await call.provide(get_llm),
        tasks=await call.provide(get_background_tasks),
        sessions=await call.provide(get_session_maker),
        user=call.user,
        brief_id=brief_id,
        idea_ids=write_request.idea_ids,
        clock=await call.provide(get_clock),
    )
    picked = set(write_request.idea_ids)
    return StartedPostsToolResponse(
        brief_id=brief.id,
        posts=[
            StartedPostToolResponse(
                id=idea.post.id, idea_id=idea.id, writing_state=idea.post.writing_state
            )
            for idea in brief.ideas
            if idea.id in picked and idea.post is not None
        ],
    )


TOOLS = [
    McpTool(plan_posts, rate=WRITE_RATE, annotations=ADDITIVE),
    McpTool(write_posts, rate=WRITE_RATE, annotations=ADDITIVE),
]
