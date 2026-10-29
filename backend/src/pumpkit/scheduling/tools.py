"""The MCP tools for Scheduled posts, over the same mediator as the router."""

from typing import Optional

from pumpkit.auth.models import User
from pumpkit.authors.x_reader import get_x_reader
from pumpkit.core.config import settings
from pumpkit.core.errors import RefusedError
from pumpkit.core.mcp_tools import (
    ADDITIVE,
    DESTRUCTIVE,
    READ_ONLY,
    READ_ONLY_RATE,
    McpTool,
    ToolCall,
)
from pumpkit.core.schemas import LinkToolResponse
from pumpkit.posts.formats import Format
from pumpkit.posts.llm import get_llm
from pumpkit.posts.schemas import WRITE_RATE as VERSION_WRITE_RATE
from pumpkit.posts.schemas import FeedbackRequest, VersionToolResponse
from pumpkit.scheduling import mediator
from pumpkit.scheduling.models import FAILED, PUBLISHED
from pumpkit.scheduling.post_status import PostStatus
from pumpkit.scheduling.publish import RETRY_WINDOW
from pumpkit.scheduling.rules import (
    DestinationChange,
    KeepDestination,
    NewScheduledPost,
    ScheduledPostEdit,
    ToCommunity,
    ToProfile,
)
from pumpkit.scheduling.schemas import (
    WRITE_RATE,
    PastCommunitiesResponse,
    PostDetailToolResponse,
    PostMessageToolResponse,
    PostNowToolResponse,
    PostsPageRequest,
    PostsPageResponse,
    ScheduledPostCreateRequest,
    ScheduledPostResponse,
    ScheduledPostToolResponse,
    ScheduledPostUpdateRequest,
)
from pumpkit.x_connection.x_publisher import get_x_publisher


def post_url(post_id: str) -> str:
    """The Post's page in the web app."""
    return f"{settings.frontend_url()}{mediator.POSTS_PAGE}/{post_id}"


def _tool_response(scheduled_post: ScheduledPostResponse) -> ScheduledPostToolResponse:
    return ScheduledPostToolResponse(
        **scheduled_post.model_dump(), post_url=post_url(scheduled_post.post_id)
    )


async def _create_scheduled_post(
    call: ToolCall[User],
    *,
    version_id: str,
    publish_at: Optional[str],
    community: Optional[str],
    share_with_followers: bool,
) -> ScheduledPostToolResponse:
    """A new Scheduled post, its arguments checked by the create route's request schema."""
    create_request = ScheduledPostCreateRequest.model_validate(
        {
            "source_version_id": version_id,
            "publish_at": publish_at,
            "publish_now": publish_at is None,
            "community": community,
            "share_with_followers": share_with_followers,
        }
    )
    new = NewScheduledPost(
        version_id=create_request.source_version_id,
        publish_at=create_request.publish_at,
        publish_now=create_request.publish_now,
        community=create_request.community,
        share_with_followers=create_request.share_with_followers,
    )
    scheduled_post = await mediator.create_scheduled_post(
        db=call.db,
        publisher=await call.provide(get_x_publisher),
        reader=await call.provide(get_x_reader),
        user=call.user,
        new=new,
        now=call.now,
    )
    return _tool_response(scheduled_post)


async def schedule_post(
    call: ToolCall[User],
    version_id: str,
    publish_at: str,
    community: Optional[str] = None,
    share_with_followers: bool = False,
) -> ScheduledPostToolResponse:
    """
    Schedule a Version's text on the User's connected X account for `publish_at`, an ISO 8601
    time with its UTC offset, on a whole minute and at least a minute from now. A Thread keeps
    every Part in order. A Post goes out once: it has at most one Scheduled post, so to change
    one already scheduled, edit it, or delete it first. The post goes to the User's profile, or
    to the Community whose URL or ID is in `community`. In a Community, `share_with_followers`
    also shows it to the User's followers.
    """
    return await _create_scheduled_post(
        call,
        version_id=version_id,
        publish_at=publish_at,
        community=community,
        share_with_followers=share_with_followers,
    )


def _post_now_message(posted: ScheduledPostToolResponse) -> str:
    """The web app's words for how Post now ended."""
    if posted.state == PUBLISHED:
        return f"Published on X: {posted.x_post_url}"
    if posted.state == FAILED:
        return f"Failed. {posted.failed_reason}"
    # Back in scheduled: X never took it, so the publisher retries it.
    minutes = int(RETRY_WINDOW.total_seconds() // 60)
    return f"X was busy. Pumpkit will keep trying for the next {minutes} minutes."


async def post_now(
    call: ToolCall[User],
    version_id: str,
    community: Optional[str] = None,
    share_with_followers: bool = False,
) -> PostNowToolResponse:
    """
    Publish a Version's text on the User's connected X account right away. Show the User the
    exact text of every Part and get their yes first. A Thread keeps every Part in order, each
    replying to the one before. A Post goes out once: one that already has a Scheduled post is
    refused. The post goes to the User's profile, or to the Community whose URL or ID is in
    `community`. In a Community, `share_with_followers` also shows it to the User's followers.
    """
    posted = await _create_scheduled_post(
        call,
        version_id=version_id,
        publish_at=None,
        community=community,
        share_with_followers=share_with_followers,
    )
    return PostNowToolResponse(**posted.model_dump(), message=_post_now_message(posted))


async def list_past_communities(call: ToolCall[User]) -> PastCommunitiesResponse:
    """
    List the Communities the User posted to before from the connected X account, most recently
    used first, to offer them for a Scheduled post.
    """
    return await mediator.list_past_communities(db=call.db, user=call.user)


def _destination_change(community: Optional[str], to_profile: bool) -> DestinationChange:
    if community is not None and to_profile:
        raise RefusedError("Give either a Community or the profile, not both.")
    if community is not None:
        return ToCommunity(pasted=community)
    if to_profile:
        return ToProfile()
    return KeepDestination()


async def edit_scheduled_post(
    call: ToolCall[User],
    scheduled_post_id: str,
    parts: Optional[list[str]] = None,
    version_id: Optional[str] = None,
    publish_at: Optional[str] = None,
    community: Optional[str] = None,
    to_profile: bool = False,
    share_with_followers: Optional[bool] = None,
) -> ScheduledPostToolResponse:
    """
    Change a waiting or Failed Scheduled post: its text, as `parts` listing every Part in
    order, or as `version_id`, another Version of the same Post whose text it then copies;
    its publish time (an ISO 8601 time with its UTC offset, which gives a Failed one another
    try); the Community whose URL or ID `community` holds, or, with `to_profile`, the User's
    profile instead. Leave out what stays the same. Live Parts of a Thread that failed partway
    are on X and locked: keep them first in `parts`, unchanged; a Version's Parts in their
    places are skipped. A new time publishes only the Parts not live, as replies to the last
    live one.
    """
    update_request = ScheduledPostUpdateRequest.model_validate(
        {
            "parts": parts,
            "source_version_id": version_id,
            "publish_at": publish_at,
            "community": community,
        }
    )
    edit = ScheduledPostEdit(
        parts=update_request.parts,
        version_id=update_request.source_version_id,
        publish_at=update_request.publish_at,
        destination=_destination_change(update_request.community, to_profile),
        share_with_followers=share_with_followers,
    )
    scheduled_post = await mediator.edit_scheduled_post(
        db=call.db,
        publisher=await call.provide(get_x_publisher),
        reader=await call.provide(get_x_reader),
        user=call.user,
        scheduled_post_id=scheduled_post_id,
        edit=edit,
        now=call.now,
    )
    return _tool_response(scheduled_post)


async def delete_scheduled_post(
    call: ToolCall[User], scheduled_post_id: str
) -> PostMessageToolResponse:
    """
    Delete a waiting or Failed Scheduled post, so it is never published, and its Post is a Draft
    again: it takes Feedback and can be scheduled anew. It can't be undone.
    """
    post_id = await mediator.cancel_scheduled_post(
        db=call.db, user=call.user, scheduled_post_id=scheduled_post_id
    )
    return PostMessageToolResponse(
        message="The Scheduled post is deleted.", post_url=post_url(post_id)
    )


async def list_posts(
    call: ToolCall[User], status: Optional[PostStatus] = None, limit: int = 20, offset: int = 0
) -> PostsPageResponse:
    """
    List the User's Posts with their status, so the User can pick one up from an earlier
    session. `status` lists one: "scheduled" (soonest first), "draft" (newest Version first),
    "published" (most recently published first) or "failed" (most recently due first); leave it
    out for every Post, newest Version first. Each Post has its Brief, its text (the Scheduled
    post's when it has one, else the latest Version's), how many Versions it has, and its
    Scheduled post's state, time, Community, failure reason and link on X. `counts` says how
    many Posts each status holds. Pages hold up to 50; pass `next_offset` as `offset` for the
    next page. `get_post` reads one Post in full.
    """
    page = PostsPageRequest(status=status, limit=limit, offset=offset)
    return await mediator.list_posts(
        db=call.db, user=call.user, status=page.status, limit=page.limit, offset=page.offset
    )


async def get_post(call: ToolCall[User], post_id: str) -> PostDetailToolResponse:
    """
    Read one of the User's Posts: its Brief and every Version in order, each with the Feedback
    that made it, its text and each Part's character count. `status` is "draft" with no
    Scheduled post, else "scheduled", "published" or "failed" from its one Scheduled post,
    returned in `scheduled_post` with its text, which the User may have edited, and the
    Version it was copied from. A Draft has no Scheduled post, so its Versions can be scheduled.
    """
    post = await mediator.get_post(db=call.db, user=call.user, post_id=post_id)
    return PostDetailToolResponse.model_validate(post.model_dump())


async def give_feedback(
    call: ToolCall[User], post_id: str, feedback: str, format: Optional[Format] = None
) -> VersionToolResponse:
    """
    Give Feedback in plain words on the latest Version of one of the User's Posts, such as
    "shorter", "end with a question" or "make Part 3 punchier", and write its next Version,
    keeping the earlier ones. `format` switches the new Version to "post" (a single X post) or
    "thread"; leave it out to keep the latest Version's Format. Only a Draft or a Failed Post
    takes Feedback: a scheduled one is edited or deleted first, and a published one is done.
    Show the User the new Version's text, with every Part and its character count. Takes up to
    a minute.
    """
    feedback_request = FeedbackRequest(feedback=feedback, format=format)
    version = await mediator.give_feedback(
        db=call.db,
        llm=await call.provide(get_llm),
        user=call.user,
        post_id=post_id,
        feedback=feedback_request.feedback,
        format=feedback_request.format,
        now=call.now,
    )
    return VersionToolResponse.model_validate(version.model_dump())


async def connect_x(call: ToolCall[User]) -> LinkToolResponse:
    """
    Where the User connects, reconnects or disconnects their X account: the Settings page of
    the Pumpkit web app, since X asks them to sign in and approve in a browser.
    """
    url = f"{settings.frontend_url()}{mediator.X_CONNECTION_PAGE}"
    return LinkToolResponse(
        message=f"Connect, reconnect or disconnect your X account on the Settings page: {url}",
        url=url,
    )


TOOLS = [
    # Reading Posts sits here because their Scheduled posts give them their status.
    McpTool(list_posts, rate=READ_ONLY_RATE, annotations=READ_ONLY),
    McpTool(get_post, rate=READ_ONLY_RATE, annotations=READ_ONLY),
    # Feedback sits with the Scheduled post tools because a Post's Scheduled post gates it.
    McpTool(give_feedback, rate=VERSION_WRITE_RATE, annotations=ADDITIVE),
    McpTool(schedule_post, rate=WRITE_RATE, annotations=ADDITIVE),
    # Post now goes through the create route on the web.
    McpTool(post_now, rate=WRITE_RATE, annotations=DESTRUCTIVE),
    # The web edit and delete routes have no limit; these take the create route's.
    McpTool(edit_scheduled_post, rate=WRITE_RATE, annotations=ADDITIVE),
    McpTool(delete_scheduled_post, rate=WRITE_RATE, annotations=DESTRUCTIVE),
    McpTool(list_past_communities, rate=READ_ONLY_RATE, annotations=READ_ONLY),
    McpTool(connect_x, rate=READ_ONLY_RATE, annotations=READ_ONLY, needs_access=False),
]
