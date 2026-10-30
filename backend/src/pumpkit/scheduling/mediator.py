from datetime import datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
from pumpkit.core.config import settings
from pumpkit.core.errors import BadRequestError, ConflictError, NotFoundError
from pumpkit.core.logging import logger
from pumpkit.core.time import as_utc
from pumpkit.posts.formats import Format, format_of
from pumpkit.posts.llm import LLM
from pumpkit.posts.models import Post
from pumpkit.posts.schemas import TextResponse, VersionResponse
from pumpkit.posts.writing.versions import write_next_version
from pumpkit.scheduling import communities, rules, service
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
    CommunityResponse,
    PastCommunitiesResponse,
    PostCountsResponse,
    PostDetailResponse,
    PostListItemResponse,
    PostsPageResponse,
    ScheduledPostPartResponse,
    ScheduledPostResponse,
    ScheduledPostSummaryResponse,
    XConnectionResponse,
)
from pumpkit.x_connection.models import XConnection
from pumpkit.x_connection.x_length import x_post_max_chars
from pumpkit.x_connection.x_publisher import XPublisher, XReconnectNeededError

# Where the User sees their Posts; one Post's page is under it.
POSTS_PAGE = "/posts"
# Where the User connects or reconnects X, which takes a browser.
X_CONNECTION_PAGE = "/settings"


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
            )
            for part in scheduled_post.parts
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
        raise NotFoundError("X has no Community with that ID. Check the URL.") from None
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


async def check_monthly_cap(
    db: AsyncSession,
    *,
    user_id: str,
    publish_at: datetime,
    part_count: int,
    excluding_id: Optional[str] = None,
) -> None:
    """
    Room for `part_count` X posts in the month. Pass `excluding_id` when changing an existing
    one, so it doesn't count itself.
    """
    cap = settings.X_POSTS_MONTHLY_CAP
    if cap is None:
        return
    start, end = rules.month_bounds(publish_at)
    count = await service.count_x_posts_between(
        db, user_id=user_id, start=start, end=end, excluding_id=excluding_id
    )
    rules.check_month_has_room(count, adding=part_count, cap=cap, moment=publish_at)


async def create_scheduled_post(
    db: AsyncSession,
    publisher: XPublisher,
    reader: XReader,
    user: User,
    new: NewScheduledPost,
    now: datetime,
) -> ScheduledPostResponse:
    """
    With `publish_now`, published within the request: Published, Failed, or back in scheduled.
    Every check that needs no twitterapi.io call runs before the Community lookup.
    """
    connection = await connection_to_publish_on(db, user_id=user.id)
    post = await version_writing.user_post(db, user=user, post_id=new.post_id)
    if await service.get_for_post(db, post_id=post.id) is not None:
        raise _already_scheduled()
    parts = _text_of(post)
    rules.check_length(parts, limit=x_post_max_chars(connection.subscription_type))
    publish_at = now if new.publish_now else rules.check_publish_at(new.publish_at, now=now)
    await check_monthly_cap(db, user_id=user.id, publish_at=publish_at, part_count=len(parts))
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
        )
    except IntegrityError:
        # Another request scheduled the same Post between the check and the insert.
        raise _already_scheduled()
    if new.publish_now:
        return await _post_now(db, publisher, scheduled_post_id=scheduled_post.id, now=now)
    await db.commit()
    return scheduled_post_response(scheduled_post)


def _already_scheduled() -> ConflictError:
    return ConflictError("This Post already has a Scheduled post. Edit it, or unschedule it first.")


def _text_of(post: Post) -> list[str]:
    """
    The Parts of the Post's Text, which a Scheduled post copies (ADR 0016), trimmed as typed
    Parts are. The User may have left a Part blank mid-edit.
    """
    if not post.text_parts:
        raise ConflictError("This Post has no Text to post. Start a new Post.")
    parts = [part.strip() for part in post.text_parts]
    rules.check_parts_written(parts)
    return parts


async def _post_now(
    db: AsyncSession, publisher: XPublisher, *, scheduled_post_id: str, now: datetime
) -> ScheduledPostResponse:
    # No commit here: publishing commits the new row along with its claim.
    await publish_scheduled_post(db, publisher, scheduled_post_id=scheduled_post_id, now=now)
    published = await service.get(db, scheduled_post_id=scheduled_post_id)
    assert published is not None
    return scheduled_post_response(published)


async def _owned(db: AsyncSession, *, user: User, scheduled_post_id: str) -> ScheduledPost:
    scheduled_post = await service.get(db, scheduled_post_id=scheduled_post_id)
    if scheduled_post is None or scheduled_post.user_id != user.id:
        raise NotFoundError("Scheduled post not found.")
    return scheduled_post


def _publishing_started() -> ConflictError:
    return ConflictError("Publishing has started, so this Scheduled post can no longer change.")


async def edit_scheduled_post(
    db: AsyncSession,
    publisher: XPublisher,
    reader: XReader,
    user: User,
    scheduled_post_id: str,
    edit: ScheduledPostEdit,
    now: datetime,
) -> ScheduledPostResponse:
    """
    New Parts or the Post's Text, time, Community or share with followers for a scheduled or Failed
    Scheduled post. A new time, or publish now, reschedules it on the X account connected now,
    so a Failed one gets another try. With publish now it answers like Post now.
    """
    scheduled_post = await _owned(db, user=user, scheduled_post_id=scheduled_post_id)
    if scheduled_post.state not in (SCHEDULED, FAILED):
        raise _publishing_started()
    live = [part.text for part in scheduled_post.parts if part.x_post_id is not None]
    parts = edit.parts
    if edit.copy_text:
        post = await version_writing.user_post(db, user=user, post_id=scheduled_post.post_id)
        # The Text's Parts in the places of the live ones are already on X as they were.
        parts = live + _text_of(post)[len(live) :]
    if parts is not None:
        rules.check_live_parts_kept(live, parts)
    reschedule = None
    connection = (
        await connection_to_publish_on(db, user_id=user.id)
        if edit.reschedules
        else await x_connections_service.get_connection(db, user_id=user.id)
    )
    if parts is not None:
        subscription_type = connection.subscription_type if connection else None
        rules.check_length(parts, limit=x_post_max_chars(subscription_type))
    part_count = len(parts if parts is not None else scheduled_post.parts)
    if connection is not None and edit.reschedules:
        new_publish_at = (
            now.replace(second=0, microsecond=0)
            if edit.publish_now
            else rules.check_publish_at(edit.publish_at, now=now)
        )
        await check_monthly_cap(
            db,
            user_id=user.id,
            publish_at=new_publish_at,
            part_count=part_count,
            excluding_id=scheduled_post_id,
        )
        reschedule = service.Reschedule(publish_at=new_publish_at, x_user_id=connection.x_user_id)
    elif part_count > len(scheduled_post.parts):
        await check_monthly_cap(
            db,
            user_id=user.id,
            publish_at=as_utc(scheduled_post.publish_at),
            part_count=part_count,
            excluding_id=scheduled_post_id,
        )
    destination = await _destination_after_edit(reader, scheduled_post, edit)
    if not await service.edit(
        db,
        scheduled_post_id=scheduled_post_id,
        parts=parts,
        reschedule=reschedule,
        destination=destination,
        now=now,
    ):
        raise _publishing_started()
    if edit.publish_now:
        return await _post_now(db, publisher, scheduled_post_id=scheduled_post_id, now=now)
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


async def cancel_scheduled_post(db: AsyncSession, user: User, scheduled_post_id: str) -> str:
    """
    Delete a scheduled or Failed Scheduled post, which makes its Post a Draft again. Returns the
    Post's id.
    """
    scheduled_post = await _owned(db, user=user, scheduled_post_id=scheduled_post_id)
    post_id = scheduled_post.post_id
    if not await service.cancel(db, scheduled_post_id=scheduled_post_id):
        raise _publishing_started()
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
    Write the Post's next Version from Feedback on its Text, which the Version then becomes. Only
    a Draft or a Failed Post takes Feedback, checked again after the model calls in case the Post
    was scheduled meanwhile. `sent_text`, the Parts the sender shows, must be the saved Text.
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
        await _check_takes_feedback(db, post_id=post_id)
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
    await db.commit()
    return version_writing.version_response(version, next_version.char_limit)


async def restore_version(
    db: AsyncSession, user: User, post_id: str, version_number: int, now: datetime
) -> TextResponse:
    """
    Make one of the Post's Versions its Text, as written. Only a Draft or a Failed Post's, and not
    while a Version is being written.
    """
    post, _ = await _post_whose_text_changes(db, user=user, post_id=post_id, now=now)
    version = next(
        (v for v in version_writing.versions_of(post) if v.version_number == version_number), None
    )
    if version is None:
        raise NotFoundError(f"This Post has no Version {version_number}.")
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
    await db.commit()
    char_limit = await version_writing.char_limit_for(db, user_id=user.id)
    text = version_writing.text_response(post, char_limit)
    # Only a Post with a Version has a Text to change.
    assert text is not None
    return text


async def _check_takes_feedback(db: AsyncSession, *, post_id: str) -> None:
    scheduled_post = await service.get_for_post(db, post_id=post_id)
    check_takes_feedback(post_status(scheduled_post.state if scheduled_post else None))


async def _x_connection_response(
    db: AsyncSession, connection: XConnection, user: User
) -> XConnectionResponse:
    return XConnectionResponse(
        handle=connection.handle,
        char_limit=x_post_max_chars(connection.subscription_type),
        needs_reconnect=connection.needs_reconnect,
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
