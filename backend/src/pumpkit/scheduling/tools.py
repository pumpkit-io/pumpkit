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
from pumpkit.posts.schemas import TextResponse, VersionResponse
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
    FeedbackRequest,
    PastCommunitiesResponse,
    PostDetailResponse,
    PostMessageToolResponse,
    PostNowToolResponse,
    PostsPageRequest,
    PostsPageResponse,
    ScheduledPostCreateRequest,
    ScheduledPostResponse,
    ScheduledPostToolResponse,
    ScheduledPostUpdateRequest,
    UsageResponse,
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
    post_id: str,
    publish_at: Optional[str],
    community: Optional[str],
    share_with_followers: bool,
) -> ScheduledPostToolResponse:
    """A new Scheduled post, its arguments checked by the create route's request schema."""
    create_request = ScheduledPostCreateRequest.model_validate(
        {
            "post_id": post_id,
            "publish_at": publish_at,
            "publish_now": publish_at is None,
            "community": community,
            "share_with_followers": share_with_followers,
        }
    )
    new = NewScheduledPost(
        post_id=create_request.post_id,
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
    post_id: str,
    publish_at: str,
    community: Optional[str] = None,
    share_with_followers: bool = False,
) -> ScheduledPostToolResponse:
    """
    Schedule the post's text on the user's connected X account for `publish_at`, an ISO 8601
    time with its UTC offset, on a whole minute and at least a minute from now. A thread keeps
    every part in order. A post goes out once: it has at most one scheduled post, so to change
    one already scheduled, edit it, or delete it first. The post goes to the user's profile, or
    to the community whose URL or ID is in `community`. In a community, `share_with_followers`
    also shows it to the user's followers.
    """
    return await _create_scheduled_post(
        call,
        post_id=post_id,
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
    post_id: str,
    community: Optional[str] = None,
    share_with_followers: bool = False,
) -> PostNowToolResponse:
    """
    Publish the post's text on the user's connected X account right away. Show the user the
    exact text of every part and get their yes first. A thread keeps every part in order, each
    replying to the one before. A post goes out once: one that already has a scheduled post is
    refused. The post goes to the user's profile, or to the community whose URL or ID is in
    `community`. In a community, `share_with_followers` also shows it to the user's followers.
    """
    posted = await _create_scheduled_post(
        call,
        post_id=post_id,
        publish_at=None,
        community=community,
        share_with_followers=share_with_followers,
    )
    return PostNowToolResponse(**posted.model_dump(), message=_post_now_message(posted))


async def list_past_communities(call: ToolCall[User]) -> PastCommunitiesResponse:
    """
    List the communities the user posted to before from the connected X account, most recently
    used first, to offer them for a scheduled post.
    """
    return await mediator.list_past_communities(db=call.db, user=call.user)


def _destination_change(community: Optional[str], to_profile: bool) -> DestinationChange:
    if community is not None and to_profile:
        raise RefusedError("Give either a community or the profile, not both.")
    if community is not None:
        return ToCommunity(pasted=community)
    if to_profile:
        return ToProfile()
    return KeepDestination()


async def edit_scheduled_post(
    call: ToolCall[User],
    scheduled_post_id: str,
    parts: Optional[list[str]] = None,
    copy_text: bool = False,
    publish_at: Optional[str] = None,
    community: Optional[str] = None,
    to_profile: bool = False,
    share_with_followers: Optional[bool] = None,
) -> ScheduledPostToolResponse:
    """
    Change a waiting or failed scheduled post: its text, as `parts` listing every part in
    order, or with `copy_text`, its post's text as it is now, after feedback on a failed post;
    its publish time (an ISO 8601 time with its UTC offset, which gives a failed one another
    try); the community whose URL or ID `community` holds, or, with `to_profile`, the user's
    profile instead. Leave out what stays the same. Live parts of a thread that failed partway
    are on X and locked: keep them first in `parts`, unchanged; the text's parts in their
    places are skipped. A new time publishes only the parts not live, as replies to the last
    live one.
    """
    update_request = ScheduledPostUpdateRequest.model_validate(
        {
            "parts": parts,
            "copy_text": copy_text,
            "publish_at": publish_at,
            "community": community,
        }
    )
    edit = ScheduledPostEdit(
        parts=update_request.parts,
        copy_text=update_request.copy_text,
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
    Delete a waiting or failed scheduled post, so it is never published, and its post is a draft
    again: it takes feedback and can be scheduled anew. It can't be undone.
    """
    post_id = await mediator.cancel_scheduled_post(
        db=call.db, user=call.user, scheduled_post_id=scheduled_post_id
    )
    return PostMessageToolResponse(
        message="The scheduled post is deleted.", post_url=post_url(post_id)
    )


async def list_posts(
    call: ToolCall[User], status: Optional[PostStatus] = None, limit: int = 20, offset: int = 0
) -> PostsPageResponse:
    """
    List the user's posts with their status, so the user can pick one up from an earlier
    session. `status` lists one: "scheduled" (soonest first), "draft" (newest version first),
    "published" (most recently published first) or "failed" (most recently due first); leave it
    out for every post, newest version first. Each post has its brief, its text (the scheduled
    post's when it has one, else the latest version's), how many versions it has, and its
    scheduled post's state, time, community, failure reason and link on X. `counts` says how
    many posts each status holds. Pages hold up to 50; pass `next_offset` as `offset` for the
    next page. `get_post` reads one post in full.
    """
    page = PostsPageRequest(status=status, limit=limit, offset=offset)
    return await mediator.list_posts(
        db=call.db, user=call.user, status=page.status, limit=page.limit, offset=page.offset
    )


async def get_post(call: ToolCall[User], post_id: str) -> PostDetailResponse:
    """
    Read one of the user's posts: its brief, its text (the text meant for X, with
    `version_number`, the version it came from, and `edited`, whether the user changed it by hand
    since) and every version in order, each with the feedback that made it, its text, each part's
    character count, when it was written and its `starting_text`: the text that feedback was
    given on, with the version it came from, when it wasn't the version before as written. `status` is "draft" with no
    scheduled post, else "scheduled", "published" or "failed" from its one scheduled post,
    returned in `scheduled_post` with its own copy of the text, which the user may have edited
    since. A draft has no scheduled post, so its text can be scheduled.
    """
    return await mediator.get_post(db=call.db, user=call.user, post_id=post_id)


async def give_feedback(
    call: ToolCall[User], post_id: str, feedback: str, format: Optional[Format] = None
) -> VersionResponse:
    """
    Give feedback in plain words on one of the user's posts, such as "shorter", "end with a
    question", "make part 3 punchier" or "like version 2, with a different hook". It rewrites
    the post's text as it is now, hand edits and a restored version included, into the next
    version, which becomes the text, keeping the earlier ones. `format` switches the new version
    to "post" (a single X post) or "thread"; leave it out to keep the text's format. Only a draft
    or a failed post takes feedback: a scheduled one is edited or deleted first, and a published
    one is done. Show the user the new version's text, with every part and its character count.
    Takes up to a minute.
    """
    feedback_request = FeedbackRequest(feedback=feedback, format=format)
    return await mediator.give_feedback(
        db=call.db,
        llm=await call.provide(get_llm),
        user=call.user,
        post_id=post_id,
        feedback=feedback_request.feedback,
        format=feedback_request.format,
        now=call.now,
    )


async def restore_version(call: ToolCall[User], post_id: str, version_number: int) -> TextResponse:
    """
    Make an earlier version of one of the user's posts its text again, by its number, without
    writing a new one: the text is then that version's text as written, and feedback rewrites it from there.
    Any hand edits to the text are replaced (`get_post` says whether it is `edited`). Every
    version stays in the post's history. Only a draft or a failed post's text changes. Answers
    with the text.
    """
    return await mediator.restore_version(
        db=call.db, user=call.user, post_id=post_id, version_number=version_number, now=call.now
    )


async def get_usage(call: ToolCall[User]) -> UsageResponse:
    """
    What the user has left of their allowance this period: generations (each post started and
    each feedback uses one), X posts (each part of a thread is one) and, of those, X posts with
    a link, each with its limit, how many are used and how many are left (a limit of null is no
    cap), `resets_at`, when the period ends: the next reset, or the trial's end, and `way_out`,
    what the user can do at a limit before then. `top_ups` lists the user's top-ups with
    something left and when each expires: they are spent only once the allowance is used up.
    `allowance` is null where there are no allowances, or the user isn't subscribed.
    """
    return await mediator.get_usage(db=call.db, user=call.user, now=call.now)


async def connect_x(call: ToolCall[User]) -> LinkToolResponse:
    """
    Where the user connects, reconnects or disconnects their X account: the Settings page of
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
    # The web restore route has no limit; this takes the create route's.
    McpTool(restore_version, rate=WRITE_RATE, annotations=ADDITIVE),
    McpTool(schedule_post, rate=WRITE_RATE, annotations=ADDITIVE),
    # Post now goes through the create route on the web.
    McpTool(post_now, rate=WRITE_RATE, annotations=DESTRUCTIVE),
    # The web edit and delete routes have no limit; these take the create route's.
    McpTool(edit_scheduled_post, rate=WRITE_RATE, annotations=ADDITIVE),
    McpTool(delete_scheduled_post, rate=WRITE_RATE, annotations=DESTRUCTIVE),
    McpTool(list_past_communities, rate=READ_ONLY_RATE, annotations=READ_ONLY),
    # Open to Users who aren't Subscribed, as `GET /usage` is: they have no Allowance.
    McpTool(get_usage, rate=READ_ONLY_RATE, annotations=READ_ONLY, needs_access=False),
    McpTool(connect_x, rate=READ_ONLY_RATE, annotations=READ_ONLY, needs_access=False),
]
