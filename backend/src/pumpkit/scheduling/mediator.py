from datetime import datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.posts.service as posts_service
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
from pumpkit.scheduling import communities, rules, service
from pumpkit.scheduling.communities import Community, Destination
from pumpkit.scheduling.models import FAILED, SCHEDULED, ScheduledPost, ScheduledPostState
from pumpkit.scheduling.publishing import publish_scheduled_post
from pumpkit.scheduling.schemas import (
    CommunityResponse,
    PastCommunitiesResponse,
    ScheduledPostResponse,
    ScheduledPostsListResponse,
    XConnectionResponse,
)
from pumpkit.x_connection.models import XConnection
from pumpkit.x_connection.x_length import x_post_max_chars
from pumpkit.x_connection.x_publisher import XPublisher, XReconnectNeededError

# Where the User connects or reconnects X, which takes a browser.
SCHEDULED_PAGE = "/scheduled"


def _community_response(community_id: str, name: Optional[str]) -> CommunityResponse:
    return CommunityResponse(
        id=community_id, name=name, url=communities.community_url(community_id)
    )


def scheduled_post_response(scheduled_post: ScheduledPost) -> ScheduledPostResponse:
    published_at = scheduled_post.published_at
    x_post_id = scheduled_post.x_post_id
    community_id = scheduled_post.community_id
    return ScheduledPostResponse(
        id=scheduled_post.id,
        text=scheduled_post.text,
        state=scheduled_post.state,
        publish_at=as_utc(scheduled_post.publish_at),
        published_at=as_utc(published_at) if published_at else None,
        # X redirects this to the post under the account's current handle.
        x_post_url=f"https://x.com/i/web/status/{x_post_id}" if x_post_id else None,
        failed_reason=scheduled_post.failed_reason,
        source_version_id=scheduled_post.source_version_id,
        community=_community_response(community_id, scheduled_post.community_name)
        if community_id
        else None,
        share_with_followers=scheduled_post.share_with_followers,
        created_at=as_utc(scheduled_post.created_at),
    )


async def look_up_community(reader: XReader, pasted: str) -> CommunityResponse:
    """The pasted Community with its name on X, or with no name when X can't be read."""
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
    return _community_response(community_id, name)


async def list_scheduled_posts(
    db: AsyncSession, user: User, state: Optional[ScheduledPostState]
) -> ScheduledPostsListResponse:
    scheduled_posts = await service.list_for_user(db, user_id=user.id, state=state)
    return ScheduledPostsListResponse(data=[scheduled_post_response(s) for s in scheduled_posts])


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
        raise ConflictError("Connect your X account first.", fix_page=SCHEDULED_PAGE)
    if connection.needs_reconnect:
        raise ConflictError(
            "X no longer accepts Pumpkit's access to your account. Reconnect X first.",
            fix_page=SCHEDULED_PAGE,
        )
    return connection


async def check_monthly_cap(
    db: AsyncSession,
    *,
    user_id: str,
    publish_at: datetime,
    excluding_id: Optional[str] = None,
) -> None:
    """Pass `excluding_id` when moving an existing one, so it doesn't count itself."""
    cap = settings.SCHEDULED_POSTS_MONTHLY_CAP
    if cap is None:
        return
    start, end = rules.month_bounds(publish_at)
    count = await service.count_publishing_between(
        db, user_id=user_id, start=start, end=end, excluding_id=excluding_id
    )
    rules.check_month_has_room(count, cap=cap, moment=publish_at)


async def create_scheduled_post(
    db: AsyncSession,
    publisher: XPublisher,
    user: User,
    text: str,
    publish_at: Optional[datetime],
    publish_now: bool,
    now: datetime,
    source_version_id: Optional[str] = None,
    destination: Destination = Destination(),
) -> ScheduledPostResponse:
    """With `publish_now`, published within the request: Published, Failed, or back in scheduled."""
    connection = await connection_to_publish_on(db, user_id=user.id)
    if destination.community is not None:
        communities.check_community_id(destination.community.id)
    rules.check_length(text, limit=x_post_max_chars(connection.subscription_type))
    publish_at = now if publish_now else rules.check_publish_at(publish_at, now=now)
    await check_monthly_cap(db, user_id=user.id, publish_at=publish_at)
    if source_version_id is not None:
        await source_version_final(db, user=user, version_id=source_version_id)
    scheduled_post = await service.create(
        db,
        user_id=user.id,
        x_user_id=connection.x_user_id,
        text=text,
        publish_at=publish_at.replace(second=0, microsecond=0) if publish_now else publish_at,
        now=now,
        source_version_id=source_version_id,
        destination=destination,
    )
    if publish_now:
        return await _post_now(db, publisher, scheduled_post_id=scheduled_post.id, now=now)
    await db.commit()
    return scheduled_post_response(scheduled_post)


async def source_version_final(db: AsyncSession, *, user: User, version_id: str) -> str:
    """The Final a Scheduled post copies from its source Version, or a 404 unless it's the User's."""
    version = await posts_service.get_user_version(db, user_id=user.id, version_id=version_id)
    if version is None or version.final is None:
        raise NotFoundError("Version not found.")
    return version.final


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
    user: User,
    scheduled_post_id: str,
    text: Optional[str],
    publish_at: Optional[datetime],
    now: datetime,
    changes_community: bool = False,
    community: Optional[Community] = None,
    share_with_followers: Optional[bool] = None,
) -> ScheduledPostResponse:
    """
    New text, time, Community or share with followers for a scheduled or Failed Scheduled post.
    A new time reschedules it on the X account connected now, so a Failed one gets another try.
    With `changes_community`, `community` replaces the current one and None means the profile.
    """
    scheduled_post = await _owned(db, user=user, scheduled_post_id=scheduled_post_id)
    if scheduled_post.state not in (SCHEDULED, FAILED):
        raise _publishing_started()
    reschedule = None
    destination = None
    if changes_community or share_with_followers is not None:
        if community is not None:
            communities.check_community_id(community.id)
        destination = _destination_after_edit(
            scheduled_post, changes_community, community, share_with_followers
        )
    connection = (
        await connection_to_publish_on(db, user_id=user.id)
        if publish_at is not None
        else await x_connections_service.get_connection(db, user_id=user.id)
    )
    if text is not None:
        subscription_type = connection.subscription_type if connection else None
        rules.check_length(text, limit=x_post_max_chars(subscription_type))
    if connection is not None and publish_at is not None:
        new_publish_at = rules.check_publish_at(publish_at, now=now)
        await check_monthly_cap(
            db, user_id=user.id, publish_at=new_publish_at, excluding_id=scheduled_post_id
        )
        reschedule = service.Reschedule(publish_at=new_publish_at, x_user_id=connection.x_user_id)
    if not await service.edit(
        db,
        scheduled_post_id=scheduled_post_id,
        text=text,
        reschedule=reschedule,
        destination=destination,
        now=now,
    ):
        raise _publishing_started()
    await db.commit()
    return scheduled_post_response(await _owned(db, user=user, scheduled_post_id=scheduled_post_id))


def _destination_after_edit(
    scheduled_post: ScheduledPost,
    changes_community: bool,
    community: Optional[Community],
    share_with_followers: Optional[bool],
) -> Destination:
    """Where the Scheduled post goes after the edit, keeping what the edit leaves unsaid."""
    if not changes_community and scheduled_post.community_id is not None:
        community = Community(id=scheduled_post.community_id, name=scheduled_post.community_name)
    if share_with_followers is None:
        share_with_followers = scheduled_post.share_with_followers
    return Destination(community=community, share_with_followers=share_with_followers)


async def cancel_scheduled_post(db: AsyncSession, user: User, scheduled_post_id: str) -> None:
    """Delete a scheduled or Failed Scheduled post."""
    await _owned(db, user=user, scheduled_post_id=scheduled_post_id)
    if not await service.cancel(db, scheduled_post_id=scheduled_post_id):
        raise _publishing_started()
    await db.commit()


async def _x_connection_response(db: AsyncSession, connection: XConnection) -> XConnectionResponse:
    return XConnectionResponse(
        handle=connection.handle,
        char_limit=x_post_max_chars(connection.subscription_type),
        needs_reconnect=connection.needs_reconnect,
        scheduled_posts_waiting=await service.count_waiting(
            db, user_id=connection.user_id, x_user_id=connection.x_user_id
        ),
    )


def _owned_elsewhere(handle: str) -> ConflictError:
    return ConflictError(f"@{handle} is already connected to another Pumpkit account.")


async def get_x_connection(db: AsyncSession, user: User) -> XConnectionResponse:
    connection = await x_connections_service.get_connection(db, user_id=user.id)
    if connection is None:
        raise x_connections_service.XConnectionNotFoundError()
    return await _x_connection_response(db, connection)


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
    return await _x_connection_response(db, connection)
