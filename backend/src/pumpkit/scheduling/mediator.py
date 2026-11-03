import asyncio
from datetime import datetime
from typing import BinaryIO, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.auth.service.users as users_service
import pumpkit.billing.service as billing_service
import pumpkit.posts.media as media_service
import pumpkit.posts.media_files as media_files
import pumpkit.posts.service as posts_service
import pumpkit.posts.version_writing as version_writing
import pumpkit.x_connection.service as x_connections_service
from pumpkit.auth.models import User
from pumpkit.authors.x_reader import (
    CommunityNotFoundError,
    XReader,
    XReaderError,
    XReaderNotConfiguredError,
)
from pumpkit.billing.allowance import COUNT_NOUNS, check_publishes_before_end
from pumpkit.billing.models import AllowanceCount
from pumpkit.core.config import settings
from pumpkit.core.errors import BadRequestError, ConflictError, NotFoundError
from pumpkit.core.logging import logger
from pumpkit.core.rate_limit import hit_user_limit
from pumpkit.core.storage import FileStorage
from pumpkit.core.time import Clock, as_utc
from pumpkit.posts.formats import Format, format_of
from pumpkit.posts.llm import LLM
from pumpkit.posts.models import Media, Post
from pumpkit.posts.schemas import MEDIA_RATE, MediaResponse, TextResponse, VersionResponse
from pumpkit.posts.writing.versions import write_next_version
from pumpkit.scheduling import communities, rules, service, top_up_charges
from pumpkit.scheduling.communities import Community, Destination
from pumpkit.scheduling.models import (
    FAILED,
    PUBLISHED,
    SCHEDULED,
    ScheduledPost,
)
from pumpkit.scheduling.post_status import (
    PostStatus,
    check_takes_feedback,
    check_text_changes,
    post_status,
)
from pumpkit.scheduling.publishing import publish_scheduled_post
from pumpkit.scheduling.rules import (
    KeepDestination,
    NewScheduledPost,
    ScheduledPostEdit,
    ToCommunity,
    ToProfile,
)
from pumpkit.scheduling.schemas import (
    AllowanceUsageResponse,
    CommunityResponse,
    PastCommunitiesResponse,
    PostCountsResponse,
    PostDetailResponse,
    PostListItemResponse,
    PostsPageResponse,
    ScheduledPostPartResponse,
    ScheduledPostResponse,
    ScheduledPostSummaryResponse,
    TopUpUsageResponse,
    UsageCountResponse,
    UsageResponse,
    XConnectionResponse,
)
from pumpkit.scheduling.top_up_charges import rebalance_top_ups
from pumpkit.x_connection.models import XConnection
from pumpkit.x_connection.x_length import x_post_max_chars
from pumpkit.x_connection.x_publisher import XPublisher, XReconnectNeededError

# Where the User sees their Posts; one Post's page is under it.
POSTS_PAGE = "/posts"
X_CONNECTION_PAGE = x_connections_service.X_CONNECTION_PAGE


def _community_response(community_id: str, name: Optional[str]) -> CommunityResponse:
    return CommunityResponse(
        id=community_id, name=name, url=communities.community_url(community_id)
    )


def _x_post_url(x_post_id: Optional[str]) -> Optional[str]:
    # X redirects this to the post under the account's current handle.
    return f"https://x.com/i/web/status/{x_post_id}" if x_post_id else None


def scheduled_post_response(scheduled_post: ScheduledPost) -> ScheduledPostResponse:
    published_at = scheduled_post.published_at
    community_id = scheduled_post.community_id
    return ScheduledPostResponse(
        id=scheduled_post.id,
        parts=[
            ScheduledPostPartResponse(
                text=part.text,
                live=part.x_post_id is not None,
                x_post_url=_x_post_url(part.x_post_id),
                media=[media_service.media_response(m) for m in media],
            )
            for part, media in zip(scheduled_post.parts, service.media_by_part(scheduled_post))
        ],
        state=scheduled_post.state,
        publish_at=as_utc(scheduled_post.publish_at),
        published_at=as_utc(published_at) if published_at else None,
        x_post_url=_x_post_url(scheduled_post.parts[0].x_post_id)
        if scheduled_post.state == PUBLISHED
        else None,
        failed_reason=scheduled_post.failed_reason,
        post_id=scheduled_post.post_id,
        community=_community_response(community_id, scheduled_post.community_name)
        if community_id
        else None,
        share_with_followers=scheduled_post.share_with_followers,
        created_at=as_utc(scheduled_post.created_at),
    )


async def look_up_community(reader: XReader, pasted: str) -> CommunityResponse:
    """The pasted Community with its name on X, or with no name when X can't be read."""
    community = await _community(reader, pasted)
    return _community_response(community.id, community.name)


async def _community(reader: XReader, pasted: str) -> Community:
    community_id = communities.community_id_from(pasted)
    try:
        name: Optional[str] = (await reader.fetch_community(community_id)).name
    except CommunityNotFoundError:
        raise NotFoundError("X has no community with that ID. Check the URL.") from None
    except XReaderNotConfiguredError:
        name = None
    except XReaderError as error:
        # The name is only a label, so a failed read mustn't stop the User posting.
        logger.warning("Looking up Community %s failed: %s", community_id, error)
        name = None
    return Community(id=community_id, name=name)


async def list_past_communities(db: AsyncSession, user: User) -> PastCommunitiesResponse:
    """Only the connected X account's: membership in a Community belongs to the X account."""
    connection = await x_connections_service.get_connection(db, user_id=user.id)
    if connection is None:
        return PastCommunitiesResponse(data=[])
    past = await service.past_communities(db, user_id=user.id, x_user_id=connection.x_user_id)
    return PastCommunitiesResponse(data=[_community_response(c.id, c.name) for c in past])


async def connection_to_publish_on(db: AsyncSession, *, user_id: str) -> XConnection:
    """The X connection a new or rescheduled Scheduled post targets, or a 409."""
    connection = await x_connections_service.get_connection(db, user_id=user_id)
    if connection is None:
        raise ConflictError("Connect your X account first.", fix_page=X_CONNECTION_PAGE)
    if connection.needs_reconnect:
        raise ConflictError(
            "X no longer accepts Pumpkit's access to your account. Reconnect X first.",
            fix_page=X_CONNECTION_PAGE,
        )
    return connection


def _growing(
    needed: rules.XPosts, before: Optional[rules.XPosts], caps: dict[AllowanceCount, Optional[int]]
) -> dict[AllowanceCount, int]:
    """The capped counts the change adds to: all it needs when new or moving, else what grows."""
    return {
        count: cap
        for count, cap in caps.items()
        if cap is not None and (before is None or getattr(needed, count) > getattr(before, count))
    }


async def check_x_posts_room(
    db: AsyncSession,
    *,
    user_id: str,
    publish_at: datetime,
    parts: list[str],
    excluding_id: Optional[str] = None,
    before: Optional[rules.XPosts] = None,
) -> None:
    """
    Room for `parts` as X posts and link posts publishing at `publish_at`: where Plans are sold,
    in its Allowance period, then the Top-ups, with every post in the period charged afresh; else
    in its UTC calendar month. Pass `excluding_id` when changing an existing one, so it doesn't
    count itself, and `before`, what it used, when it stays in place, so only what grows is
    checked. A new or moved one must publish before a cancelled Subscription ends.
    """
    needed = rules.x_posts_in(parts)
    if billing_service.sells_plans():
        allowance = await billing_service.get_allowance(db, user_id=user_id, moment=publish_at)
        if allowance is None:
            return
        if before is None:
            check_publishes_before_end(allowance, publish_at)
        growing = _growing(
            needed,
            before,
            {"x_posts": allowance.limits.x_posts, "link_x_posts": allowance.limits.link_x_posts},
        )
        if growing:
            await top_up_charges.check_room(
                db,
                user_id=user_id,
                allowance=allowance,
                publish_at=publish_at,
                needed=needed,
                limits=growing,
                changing_id=excluding_id,
            )
        return
    caps: dict[AllowanceCount, Optional[int]] = {
        "x_posts": settings.X_POSTS_MONTHLY_CAP,
        "link_x_posts": settings.X_LINK_POSTS_MONTHLY_CAP,
    }
    start, end = rules.month_bounds(publish_at)
    used = await service.x_posts_used_between(
        db,
        user_id=user_id,
        start=start,
        end=end,
        excluding=[excluding_id] if excluding_id is not None else (),
    )
    for count, cap in _growing(needed, before, caps).items():
        rules.check_month_has_room(
            getattr(used, count),
            adding=getattr(needed, count),
            cap=cap,
            moment=publish_at,
            noun=COUNT_NOUNS[count],
        )


def _usage_count(limit: Optional[int], used: int) -> UsageCountResponse:
    return UsageCountResponse(
        limit=limit, used=used, left=None if limit is None else max(0, limit - used)
    )


async def get_usage(db: AsyncSession, user: User, at: datetime) -> UsageResponse:
    """The User's usage in the Allowance period holding `at`, with the Top-ups unexpired then."""
    at = as_utc(at)
    allowance = await billing_service.get_allowance(db, user_id=user.id, moment=at)
    if allowance is None:
        return UsageResponse(allowance=None)
    period = allowance.period
    used = await service.x_posts_used_between(
        db, user_id=user.id, start=period.start, end=period.end
    )
    generations = await posts_service.count_versions_between(
        db, user_id=user.id, start=period.start, end=period.end
    )
    return UsageResponse(
        allowance=AllowanceUsageResponse(
            trial=period.trial,
            resets_at=period.end,
            resets_on_day=period.reset_day,
            generations=_usage_count(allowance.limits.generations, generations),
            x_posts=_usage_count(allowance.limits.x_posts, used.x_posts),
            link_x_posts=_usage_count(allowance.limits.link_x_posts, used.link_x_posts),
            way_out=allowance.way_out,
            top_ups=[
                TopUpUsageResponse(
                    generations_left=top_up.left_or_none("generations"),
                    x_posts_left=top_up.left_or_none("x_posts"),
                    link_x_posts_left=top_up.left_or_none("link_x_posts"),
                    expires_at=top_up.expires_at,
                )
                for top_up in await billing_service.top_up_balances(db, user_id=user.id, moment=at)
                if top_up.has_left()
            ],
            may_buy_top_up=allowance.way_out == "top_up",
        )
    )


async def create_scheduled_post(
    db: AsyncSession,
    publisher: XPublisher,
    storage: FileStorage,
    reader: XReader,
    user: User,
    new: NewScheduledPost,
    clock: Clock,
) -> ScheduledPostResponse:
    """
    With `publish_now`, published within the request: Published, Failed, or back in scheduled.
    Every check that needs no twitterapi.io call runs before the Community lookup.
    """
    now = clock()
    connection = await connection_to_publish_on(db, user_id=user.id)
    # Serializes the User's checks and charges of X posts until the commit.
    await users_service.lock_user_id(db, user_id=user.id)
    post = await version_writing.user_post(db, user=user, post_id=new.post_id)
    if await service.get_for_post(db, post_id=post.id) is not None:
        raise _already_scheduled()
    parts = _text_of(post)
    rules.check_length(parts, limit=x_post_max_chars(connection.subscription_type))
    media = media_service.text_media_by_part(post)
    await _check_media(db, media, user_id=user.id)
    publish_at = now if new.publish_now else rules.check_publish_at(new.publish_at, now=now)
    await check_x_posts_room(db, user_id=user.id, publish_at=publish_at, parts=parts)
    community = await _community(reader, new.community) if new.community is not None else None
    try:
        scheduled_post = await service.create(
            db,
            user_id=user.id,
            x_user_id=connection.x_user_id,
            post_id=post.id,
            parts=parts,
            publish_at=publish_at.replace(second=0, microsecond=0)
            if new.publish_now
            else publish_at,
            now=now,
            destination=Destination(
                community=community, share_with_followers=new.share_with_followers
            ),
            media=_ids(media),
        )
    except IntegrityError:
        # Another request scheduled the same Post between the check and the insert.
        raise _already_scheduled()
    await rebalance_top_ups(db, user_id=user.id, moments=[as_utc(scheduled_post.publish_at)])
    if new.publish_now:
        return await _post_now(
            db, publisher, storage, scheduled_post_id=scheduled_post.id, now=now, clock=clock
        )
    await db.commit()
    return scheduled_post_response(scheduled_post)


async def _check_media(
    db: AsyncSession, media: list[list[Media]], *, user_id: str, live_count: int = 0
) -> None:
    """The Media the Parts not live will go out with fits X, is still stored, and can go out."""
    rules.check_media([[m.kind for m in part] for part in media])
    rules.check_media_kept(
        [[m.file_key is not None for m in part] for part in media], live_count=live_count
    )
    rules.check_media_once(_ids(media))
    if any(media[live_count:]):
        await x_connections_service.check_takes_media(db, user_id=user_id)


def _ids(media: list[list[Media]]) -> list[list[str]]:
    return [[m.id for m in part] for part in media]


def _media_after_edit(
    scheduled_post: ScheduledPost, post: Optional[Post], part_count: int
) -> list[list[Media]]:
    """
    Each Part's Media once the edit's Parts replace the ones not live: the Text's from the Post
    `post` copied, else the Scheduled post's own, each staying with the Part in its place.
    """
    current = service.media_by_part(scheduled_post)
    live_count = sum(1 for part in scheduled_post.parts if part.x_post_id is not None)
    if post is not None:
        text = media_service.text_media_by_part(post)
        return current[:live_count] + text[live_count:part_count]
    rules.check_part_count_kept_with_media(
        [bool(part) for part in current], live_count=live_count, part_count=part_count
    )
    return current[:part_count] + [[] for _ in range(part_count - len(current))]


def _already_scheduled() -> ConflictError:
    return ConflictError("This post already has a scheduled post. Edit it, or unschedule it first.")


def _text_of(post: Post) -> list[str]:
    """
    The Parts of the Post's Text, which a Scheduled post copies (ADR 0016), trimmed as typed
    Parts are. The User may have left a Part blank mid-edit.
    """
    if not post.text_parts:
        raise ConflictError("This post has no text to post. Start a new post.")
    parts = [part.strip() for part in post.text_parts]
    rules.check_parts_written(parts)
    return parts


async def _post_now(
    db: AsyncSession,
    publisher: XPublisher,
    storage: FileStorage,
    *,
    scheduled_post_id: str,
    now: datetime,
    clock: Clock,
) -> ScheduledPostResponse:
    # No commit here: publishing commits the new row along with its claim.
    await publish_scheduled_post(
        db,
        publisher,
        storage,
        scheduled_post_id=scheduled_post_id,
        now=now,
        clock=clock,
    )
    published = await service.get_existing(db, scheduled_post_id=scheduled_post_id)
    return scheduled_post_response(published)


async def _owned(db: AsyncSession, *, user: User, scheduled_post_id: str) -> ScheduledPost:
    scheduled_post = await service.get(db, scheduled_post_id=scheduled_post_id)
    if scheduled_post is None or scheduled_post.user_id != user.id:
        raise NotFoundError("Scheduled post not found.")
    return scheduled_post


def _publishing_started() -> ConflictError:
    return ConflictError("Publishing has started, so this scheduled post can no longer change.")


async def edit_scheduled_post(
    db: AsyncSession,
    publisher: XPublisher,
    storage: FileStorage,
    reader: XReader,
    user: User,
    scheduled_post_id: str,
    edit: ScheduledPostEdit,
    clock: Clock,
) -> ScheduledPostResponse:
    """
    New Parts or the Post's Text, time, Community or share with followers for a scheduled or Failed
    Scheduled post. A new time, or publish now, reschedules it on the X account connected now,
    so a Failed one gets another try. With publish now it answers like Post now.
    """
    now = clock()
    await users_service.lock_user_id(db, user_id=user.id)
    scheduled_post = await _owned(db, user=user, scheduled_post_id=scheduled_post_id)
    if scheduled_post.state not in (SCHEDULED, FAILED):
        raise _publishing_started()
    publish_at_before = as_utc(scheduled_post.publish_at)
    live = [part.text for part in scheduled_post.parts if part.x_post_id is not None]
    parts = edit.parts
    post = None
    if edit.copy_text:
        post = await version_writing.user_post(db, user=user, post_id=scheduled_post.post_id)
        # The Text's Parts in the places of the live ones are already on X as they were.
        parts = live + _text_of(post)[len(live) :]
    media = None
    if parts is not None:
        rules.check_live_parts_kept(live, parts)
        media = _media_after_edit(scheduled_post, post, len(parts))
        await _check_media(db, media, user_id=user.id, live_count=len(live))
    elif edit.reschedules:
        await _check_media(
            db, service.media_by_part(scheduled_post), user_id=user.id, live_count=len(live)
        )
    reschedule = None
    connection = (
        await connection_to_publish_on(db, user_id=user.id)
        if edit.reschedules
        else await x_connections_service.get_connection(db, user_id=user.id)
    )
    if parts is not None:
        subscription_type = connection.subscription_type if connection else None
        rules.check_length(parts, limit=x_post_max_chars(subscription_type))
    current = [part.text for part in scheduled_post.parts]
    if connection is not None and edit.reschedules:
        new_publish_at = (
            now.replace(second=0, microsecond=0)
            if edit.publish_now
            else rules.check_publish_at(edit.publish_at, now=now)
        )
        await check_x_posts_room(
            db,
            user_id=user.id,
            publish_at=new_publish_at,
            parts=parts if parts is not None else current,
            excluding_id=scheduled_post_id,
        )
        reschedule = service.Reschedule(publish_at=new_publish_at, x_user_id=connection.x_user_id)
    elif parts is not None and scheduled_post.state == SCHEDULED:
        # A Failed one left in place publishes nothing more, so its new Parts cost nothing yet.
        await check_x_posts_room(
            db,
            user_id=user.id,
            publish_at=as_utc(scheduled_post.publish_at),
            parts=parts,
            excluding_id=scheduled_post_id,
            before=rules.x_posts_in(current),
        )
    destination = await _destination_after_edit(reader, scheduled_post, edit)
    if not await service.edit(
        db,
        scheduled_post_id=scheduled_post_id,
        parts=parts,
        reschedule=reschedule,
        destination=destination,
        now=now,
        media=_ids(media) if media is not None else None,
    ):
        raise _publishing_started()
    moments = [publish_at_before, reschedule.publish_at] if reschedule else [publish_at_before]
    await rebalance_top_ups(db, user_id=user.id, moments=moments)
    if edit.publish_now:
        return await _post_now(
            db, publisher, storage, scheduled_post_id=scheduled_post_id, now=now, clock=clock
        )
    await db.commit()
    return scheduled_post_response(await _owned(db, user=user, scheduled_post_id=scheduled_post_id))


async def _destination_after_edit(
    reader: XReader, scheduled_post: ScheduledPost, edit: ScheduledPostEdit
) -> Optional[Destination]:
    """Where the Scheduled post goes after the edit, keeping what it leaves unsaid; None if unchanged."""
    change = edit.destination
    if isinstance(change, KeepDestination) and edit.share_with_followers is None:
        return None
    community: Optional[Community]
    match change:
        case ToCommunity(pasted=pasted):
            community = await _community(reader, pasted)
        case ToProfile():
            community = None
        case KeepDestination():
            community = (
                Community(id=scheduled_post.community_id, name=scheduled_post.community_name)
                if scheduled_post.community_id is not None
                else None
            )
    share_with_followers = edit.share_with_followers
    if share_with_followers is None:
        share_with_followers = scheduled_post.share_with_followers
    return Destination(community=community, share_with_followers=share_with_followers)


async def cancel_scheduled_post(
    db: AsyncSession, user: User, scheduled_post_id: str, now: datetime
) -> str:
    """
    Delete a scheduled or Failed Scheduled post, which makes its Post a Draft again. Its live
    Parts keep counting as X posts, with what they took from Top-ups. Returns the Post's id.
    """
    await users_service.lock_user_id(db, user_id=user.id)
    scheduled_post = await _owned(db, user=user, scheduled_post_id=scheduled_post_id)
    post_id = scheduled_post.post_id
    publish_at = as_utc(scheduled_post.publish_at)
    if any(part.x_post_id for part in scheduled_post.parts):
        if not await top_up_charges.keep_live_parts_counted(
            db, user_id=user.id, scheduled_post_id=scheduled_post_id, publish_at=publish_at, now=now
        ):
            raise _publishing_started()
    # Postgres cascades this from the delete; SQLite skips foreign keys without a pragma.
    await billing_service.give_back_charges(db, scheduled_post_id=scheduled_post_id)
    if not await service.cancel(db, scheduled_post_id=scheduled_post_id):
        raise _publishing_started()
    await rebalance_top_ups(db, user_id=user.id, moments=[publish_at])
    await db.commit()
    return post_id


async def get_post(db: AsyncSession, user: User, post_id: str) -> PostDetailResponse:
    """The User's Post with its Text, every Version in order, its status and Scheduled post."""
    post = await version_writing.user_post(db, user=user, post_id=post_id)
    char_limit = await version_writing.char_limit_for(db, user_id=user.id)
    scheduled_post = await service.get_for_post(db, post_id=post_id)
    return PostDetailResponse(
        id=post.id,
        brief=post.brief,
        text=version_writing.text_response(post, char_limit),
        versions=[
            version_writing.version_response(v, char_limit)
            for v in version_writing.versions_of(post)
        ],
        status=post_status(scheduled_post.state if scheduled_post else None),
        scheduled_post=scheduled_post_response(scheduled_post) if scheduled_post else None,
    )


def _scheduled_post_summary(scheduled_post: ScheduledPost) -> ScheduledPostSummaryResponse:
    published_at = scheduled_post.published_at
    community_id = scheduled_post.community_id
    return ScheduledPostSummaryResponse(
        id=scheduled_post.id,
        state=scheduled_post.state,
        publish_at=as_utc(scheduled_post.publish_at),
        published_at=as_utc(published_at) if published_at else None,
        community=_community_response(community_id, scheduled_post.community_name)
        if community_id
        else None,
        share_with_followers=scheduled_post.share_with_followers,
        failed_reason=scheduled_post.failed_reason,
        x_post_url=_x_post_url(scheduled_post.parts[0].x_post_id),
    )


def _post_list_item(listed: service.ListedPost) -> PostListItemResponse:
    post, scheduled_post = listed.post, listed.scheduled_post
    versions = version_writing.versions_of(post)
    latest = versions[-1]
    if scheduled_post is not None:
        parts = [part.text for part in scheduled_post.parts]
        format = format_of(parts)
    else:
        parts = list(latest.parts or [])
        format = latest.format
    return PostListItemResponse(
        id=post.id,
        brief=post.brief,
        status=post_status(scheduled_post.state if scheduled_post else None),
        parts=parts,
        format=format,
        version_count=len(versions),
        latest_version_at=as_utc(latest.created_at),
        scheduled_post=_scheduled_post_summary(scheduled_post) if scheduled_post else None,
    )


async def list_posts(
    db: AsyncSession, user: User, status: Optional[PostStatus], limit: int, offset: int
) -> PostsPageResponse:
    """A page of the User's Posts in `status`, or every one, with how many each status holds."""
    # One past the page tells whether another page follows.
    listed = await service.list_posts(
        db, user_id=user.id, status=status, limit=limit + 1, offset=offset
    )
    counts = await service.count_posts(db, user_id=user.id)
    return PostsPageResponse(
        data=[_post_list_item(item) for item in listed[:limit]],
        counts=PostCountsResponse(**counts),
        next_offset=offset + limit if len(listed) > limit else None,
    )


async def give_feedback(
    db: AsyncSession,
    llm: LLM,
    user: User,
    post_id: str,
    feedback: str,
    format: Optional[Format],
    now: datetime,
    sent_text: Optional[list[str]] = None,
) -> VersionResponse:
    """
    Write the Post's next Version from Feedback on its Text; `sent_text` must be the saved Text.
    Takes-Feedback and Media checks run again after the model calls, under the Post's lock.
    """
    post = await version_writing.user_post(db, user=user, post_id=post_id, for_update=True)
    await _check_takes_feedback(db, post_id=post_id)
    next_version = await version_writing.prepare_next_version(
        db, user=user, post=post, format=format, sent_text=sent_text, now=now
    )
    # Holds the Text and ends the transaction before the calls, which can take minutes.
    await db.commit()

    try:
        written = await write_next_version(
            llm,
            next_version.corpus,
            post.brief,
            next_version.earlier,
            next_version.starting_text,
            feedback,
            next_version.format,
            next_version.char_limit,
        )
        # The Post may have been scheduled, or its Media changed, during the calls.
        post = await version_writing.user_post(db, user=user, post_id=post_id, for_update=True)
        scheduled_post = await _check_takes_feedback(db, post_id=post_id)
        media_service.check_dropped_parts_media_movable(
            post, part_count=len(written.parts), live_count=_live_count(scheduled_post)
        )
    except Exception as error:
        await version_writing.record_failed_attempt(
            db,
            post=post,
            sequence=next_version.sequence,
            feedback=feedback,
            format=next_version.format,
            error=error,
            now=now,
        )
        # Commit before re-raising, or the request session rolls the failed attempt back.
        await db.commit()
        raise

    version = await posts_service.record_version(
        db,
        post=post,
        sequence=next_version.sequence,
        version_number=next_version.number,
        feedback=feedback,
        written=written,
        now=now,
        starting_text=next_version.starting_text,
    )
    await version_writing.charge_generation(db, user_id=user.id, version=version, now=now)
    await db.commit()
    return version_writing.version_response(version, next_version.char_limit)


async def restore_version(
    db: AsyncSession, user: User, post_id: str, version_number: int, now: datetime
) -> TextResponse:
    """
    Make one of the Post's Versions its Text, as written. Only a Draft or a Failed Post's, and not
    while a Version is being written.
    """
    post, scheduled_post = await _post_whose_text_changes(db, user=user, post_id=post_id, now=now)
    version = next(
        (v for v in version_writing.versions_of(post) if v.version_number == version_number), None
    )
    if version is None:
        raise NotFoundError(f"This post has no version {version_number}.")
    media_service.check_dropped_parts_media_movable(
        post, part_count=len(version.parts or []), live_count=_live_count(scheduled_post)
    )
    posts_service.set_text_from_version(post, version)
    return await _commit_text(db, user=user, post=post)


async def edit_text(
    db: AsyncSession, user: User, post_id: str, parts: list[str], now: datetime
) -> TextResponse:
    """
    Store the User's Parts as the Post's Text. Only a Draft or a Failed Post's, and not while a
    Version is being written. Saving the same Parts again changes nothing, so the web app can
    retry a save.
    """
    post, scheduled_post = await _post_whose_text_changes(db, user=user, post_id=post_id, now=now)
    if scheduled_post is not None:
        live_count = sum(1 for part in scheduled_post.parts if part.x_post_id is not None)
        rules.check_text_keeps_live_parts(live_count, post.text_parts or [], parts)
    posts_service.edit_text(post, parts)
    return await _commit_text(db, user=user, post=post)


async def attach_text_media(
    db: AsyncSession,
    storage: FileStorage,
    user: User,
    post_id: str,
    part_number: int,
    file: BinaryIO,
    byte_size: int,
    now: datetime,
) -> MediaResponse:
    """
    Attach the file to Part `part_number` of the Post's Text, last among its Media, once it is
    an image Pumpkit takes and the Part has room. Only a Draft or a Failed Post's, on a Part not
    live on X. Allowed while Feedback writes a Version, which leaves the Text's Media as it is.
    """
    post, scheduled_post = await _post_whose_media_changes(db, user=user, post_id=post_id)
    part_index = part_number - 1
    _check_not_live(scheduled_post, part_index=part_index)
    media_service.check_text_part_room(post, part_index=part_index)
    checked = await asyncio.to_thread(media_files.check_image, file, byte_size)
    media = await media_service.attach_to_text(
        db, storage, post=post, part_index=part_index, checked=checked, file=file, now=now
    )
    async with media_service.files_deleted_on_failure(storage, media):
        await db.commit()
    return media_service.media_response(media)


async def start_media_upload(db: AsyncSession, user: User) -> None:
    """
    Before an upload's body arrives: refuse it, uncounted, if X must be reconnected for Media, then
    count it against the rate and commit, so no connection stays held while the upload streams.
    """
    await x_connections_service.check_takes_media(db, user_id=user.id)
    hit_user_limit("attach_text_media", user.id, MEDIA_RATE)
    await db.commit()


async def remove_text_media(db: AsyncSession, user: User, post_id: str, media_id: str) -> None:
    """Take the Media off the Post's Text. Only a Draft or a Failed Post's, on a Part not live."""
    post, scheduled_post = await _post_whose_media_changes(db, user=user, post_id=post_id)
    placed = media_service.text_media_on(post, media_id=media_id)
    _check_not_live(scheduled_post, part_index=placed.part_index)
    media_service.remove_from_text(post, placed)
    await db.commit()


async def attach_scheduled_post_media(
    db: AsyncSession,
    storage: FileStorage,
    user: User,
    scheduled_post_id: str,
    part_number: int,
    file: BinaryIO,
    byte_size: int,
    now: datetime,
) -> MediaResponse:
    """
    Attach the file to Part `part_number` of a scheduled or Failed Scheduled post's own copy, last
    among its Media, once it is an image Pumpkit takes and the Part has room. The Text keeps its own.
    """
    scheduled_post, media = await _scheduled_post_whose_media_changes(
        db, user=user, scheduled_post_id=scheduled_post_id
    )
    part_index = part_number - 1
    if not 0 <= part_index < len(media):
        raise NotFoundError(f"This scheduled post has no part {part_number}.")
    _check_not_live(scheduled_post, part_index=part_index)
    media_service.check_part_room(media, part_index=part_index)
    checked = await asyncio.to_thread(media_files.check_image, file, byte_size)
    attached = await media_service.store(
        db, storage, user_id=user.id, checked=checked, file=file, now=now
    )
    async with media_service.files_deleted_on_failure(storage, attached):
        media[part_index].append(attached)
        await _save_scheduled_post_media(
            db, scheduled_post_id=scheduled_post_id, media=media, now=now
        )
    return media_service.media_response(attached)


async def remove_scheduled_post_media(
    db: AsyncSession, user: User, scheduled_post_id: str, media_id: str, now: datetime
) -> None:
    """Take the Media off a scheduled or Failed Scheduled post's Part not live; the Text keeps its."""
    scheduled_post, media = await _scheduled_post_whose_media_changes(
        db, user=user, scheduled_post_id=scheduled_post_id
    )
    part_index = next(
        (i for i, on_part in enumerate(media) if any(m.id == media_id for m in on_part)), None
    )
    if part_index is None:
        raise NotFoundError("This scheduled post has no such media.")
    _check_not_live(scheduled_post, part_index=part_index)
    media[part_index] = [m for m in media[part_index] if m.id != media_id]
    await _save_scheduled_post_media(db, scheduled_post_id=scheduled_post_id, media=media, now=now)


async def _scheduled_post_whose_media_changes(
    db: AsyncSession, *, user: User, scheduled_post_id: str
) -> tuple[ScheduledPost, list[list[Media]]]:
    """The User's Scheduled post with each Part's Media, once its Media may change."""
    # Serializes with the User's edits, which carry the Media they read over to the new Parts.
    await users_service.lock_user_id(db, user_id=user.id)
    scheduled_post = await _owned(db, user=user, scheduled_post_id=scheduled_post_id)
    if scheduled_post.state not in (SCHEDULED, FAILED):
        raise _publishing_started()
    return scheduled_post, service.media_by_part(scheduled_post)


async def _save_scheduled_post_media(
    db: AsyncSession, *, scheduled_post_id: str, media: list[list[Media]], now: datetime
) -> None:
    # The edit only applies while the publisher hasn't claimed it since it was read.
    if not await service.edit(
        db,
        scheduled_post_id=scheduled_post_id,
        parts=None,
        reschedule=None,
        now=now,
        media=_ids(media),
    ):
        raise _publishing_started()
    await db.commit()


async def _post_whose_media_changes(
    db: AsyncSession, *, user: User, post_id: str
) -> tuple[Post, Optional[ScheduledPost]]:
    """The User's Post, locked, with its Scheduled post, once its Text's Media may change."""
    post = await version_writing.user_post(db, user=user, post_id=post_id, for_update=True)
    scheduled_post = await service.get_for_post(db, post_id=post_id)
    check_text_changes(post_status(scheduled_post.state if scheduled_post else None))
    return post, scheduled_post


def _check_not_live(scheduled_post: Optional[ScheduledPost], *, part_index: int) -> None:
    """On a Failed Post, the Parts already on X went out with the Media they had."""
    if part_index < _live_count(scheduled_post):
        raise ConflictError(f"Part {part_index + 1} is already on X, so its media is set.")


def _live_count(scheduled_post: Optional[ScheduledPost]) -> int:
    if scheduled_post is None:
        return 0
    return sum(1 for part in scheduled_post.parts if part.x_post_id is not None)


async def _post_whose_text_changes(
    db: AsyncSession, *, user: User, post_id: str, now: datetime
) -> tuple[Post, Optional[ScheduledPost]]:
    """The User's Post, locked, with its Scheduled post, once its Text may change."""
    post = await version_writing.user_post(db, user=user, post_id=post_id, for_update=True)
    scheduled_post = await service.get_for_post(db, post_id=post_id)
    check_text_changes(post_status(scheduled_post.state if scheduled_post else None))
    posts_service.check_not_writing(post, now=now)
    return post, scheduled_post


async def _commit_text(db: AsyncSession, *, user: User, post: Post) -> TextResponse:
    char_limit = await version_writing.char_limit_for(db, user_id=user.id)
    text = version_writing.text_response(post, char_limit)
    # Only a Post with a Version has a Text to change.
    if text is None:
        raise RuntimeError(f"Post {post.id} has a changed Text but no Version.")
    await db.commit()
    return text


async def _check_takes_feedback(db: AsyncSession, *, post_id: str) -> Optional[ScheduledPost]:
    scheduled_post = await service.get_for_post(db, post_id=post_id)
    check_takes_feedback(post_status(scheduled_post.state if scheduled_post else None))
    return scheduled_post


async def _x_connection_response(
    db: AsyncSession, connection: XConnection, user: User
) -> XConnectionResponse:
    return XConnectionResponse(
        handle=connection.handle,
        char_limit=x_post_max_chars(connection.subscription_type),
        needs_reconnect=connection.needs_reconnect,
        needs_reconnect_for_media=x_connections_service.needs_reconnect_for_media(connection),
        scheduled_posts_waiting=await service.count_waiting(
            db, user_id=connection.user_id, x_user_id=connection.x_user_id
        ),
        photo_url=connection.photo_url,
        offer_photo=x_connections_service.offers_photo(connection, user),
    )


def _owned_elsewhere(handle: str) -> ConflictError:
    return ConflictError(f"@{handle} is already connected to another Pumpkit account.")


async def get_x_connection(db: AsyncSession, user: User) -> XConnectionResponse:
    connection = await x_connections_service.get_connection(db, user_id=user.id)
    if connection is None:
        raise x_connections_service.XConnectionNotFoundError()
    return await _x_connection_response(db, connection, user)


async def complete_x_authorization(
    db: AsyncSession, publisher: XPublisher, user: User, code: str, state: str, now: datetime
) -> XConnectionResponse:
    """Replaces the User's X connection, whichever X account it was for."""
    user_id = user.id
    code_verifier = await x_connections_service.consume(db, user_id=user_id, state=state, now=now)
    # Commit the delete before calling X: the state is then spent even if X fails, and no
    # transaction stays open across X's calls.
    await db.commit()
    if code_verifier is None:
        raise BadRequestError("This X authorization expired or was already used. Connect X again.")

    try:
        tokens = await publisher.exchange_code(code=code, code_verifier=code_verifier, now=now)
        account = await publisher.fetch_account(access_token=tokens.access_token)
    except XReconnectNeededError:
        raise BadRequestError("X didn't give Pumpkit access to your account. Connect X again.")

    # The grant isn't revoked here: X may scope revocation to the account, cutting off its owner.
    owner = await x_connections_service.get_connection_by_x_user_id(db, x_user_id=account.user_id)
    if owner is not None and owner.user_id != user_id:
        raise _owned_elsewhere(account.handle)
    try:
        connection = await x_connections_service.save_connection(
            db, user_id=user_id, account=account, tokens=tokens, now=now
        )
        await db.commit()
    except IntegrityError:
        # Another User connected the same X account between the check and the save.
        raise _owned_elsewhere(account.handle)
    return await _x_connection_response(db, connection, user)
