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
from pumpkit.posts.formats import Format
from pumpkit.posts.llm import LLM
from pumpkit.posts.models import VersionAttempt
from pumpkit.posts.schemas import VersionResponse
from pumpkit.scheduling import communities, rules, service
from pumpkit.scheduling.communities import Community, Destination
from pumpkit.scheduling.models import (
    FAILED,
    PUBLISHED,
    SCHEDULED,
    ScheduledPost,
    ScheduledPostState,
)
from pumpkit.scheduling.post_status import check_takes_feedback, post_status
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
    PostDetailResponse,
    ScheduledPostPartResponse,
    ScheduledPostResponse,
    ScheduledPostsListResponse,
    XConnectionResponse,
)
from pumpkit.x_connection.models import XConnection
from pumpkit.x_connection.x_length import x_post_max_chars
from pumpkit.x_connection.x_publisher import XPublisher, XReconnectNeededError

# Where the User connects or reconnects X, which takes a browser.
SCHEDULED_PAGE = "/posts"


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
        source_version_id=scheduled_post.source_version_id,
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
    version = await _source_version(db, user=user, version_id=new.version_id)
    if await service.get_for_post(db, post_id=version.post_id) is not None:
        raise _already_scheduled()
    parts = list(version.final_parts or [])
    rules.check_length(parts, limit=x_post_max_chars(connection.subscription_type))
    publish_at = now if new.publish_now else rules.check_publish_at(new.publish_at, now=now)
    await check_monthly_cap(db, user_id=user.id, publish_at=publish_at, part_count=len(parts))
    community = await _community(reader, new.community) if new.community is not None else None
    try:
        scheduled_post = await service.create(
            db,
            user_id=user.id,
            x_user_id=connection.x_user_id,
            post_id=version.post_id,
            source_version_id=version.id,
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


async def _source_version(db: AsyncSession, *, user: User, version_id: str) -> VersionAttempt:
    """The Version a Scheduled post copies, or a 404 unless the Version is the User's."""
    version = await posts_service.get_user_version(db, user_id=user.id, version_id=version_id)
    if version is None or not version.final_parts:
        raise NotFoundError("Version not found.")
    return version


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
    reader: XReader,
    user: User,
    scheduled_post_id: str,
    edit: ScheduledPostEdit,
    now: datetime,
) -> ScheduledPostResponse:
    """
    New Parts, time, Community or share with followers for a scheduled or Failed Scheduled post.
    A new time reschedules it on the X account connected now, so a Failed one gets another try.
    """
    scheduled_post = await _owned(db, user=user, scheduled_post_id=scheduled_post_id)
    if scheduled_post.state not in (SCHEDULED, FAILED):
        raise _publishing_started()
    if edit.parts is not None:
        live = [part.text for part in scheduled_post.parts if part.x_post_id is not None]
        rules.check_live_parts_kept(live, edit.parts)
    reschedule = None
    connection = (
        await connection_to_publish_on(db, user_id=user.id)
        if edit.publish_at is not None
        else await x_connections_service.get_connection(db, user_id=user.id)
    )
    if edit.parts is not None:
        subscription_type = connection.subscription_type if connection else None
        rules.check_length(edit.parts, limit=x_post_max_chars(subscription_type))
    part_count = len(edit.parts if edit.parts is not None else scheduled_post.parts)
    if connection is not None and edit.publish_at is not None:
        new_publish_at = rules.check_publish_at(edit.publish_at, now=now)
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
        parts=edit.parts,
        reschedule=reschedule,
        destination=destination,
        now=now,
    ):
        raise _publishing_started()
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


async def cancel_scheduled_post(db: AsyncSession, user: User, scheduled_post_id: str) -> None:
    """Delete a scheduled or Failed Scheduled post, which makes its Post a Draft again."""
    await _owned(db, user=user, scheduled_post_id=scheduled_post_id)
    if not await service.cancel(db, scheduled_post_id=scheduled_post_id):
        raise _publishing_started()
    await db.commit()


async def get_post(db: AsyncSession, user: User, post_id: str) -> PostDetailResponse:
    """The User's Post with every Version in order, its status and its Scheduled post."""
    post = await version_writing.user_post(db, user=user, post_id=post_id)
    char_limit = await version_writing.char_limit_for(db, user_id=user.id)
    scheduled_post = await service.get_for_post(db, post_id=post_id)
    return PostDetailResponse(
        id=post.id,
        brief=post.brief,
        versions=[
            version_writing.version_response(v, char_limit)
            for v in version_writing.versions_of(post)
        ],
        status=post_status(scheduled_post.state if scheduled_post else None),
        scheduled_post=scheduled_post_response(scheduled_post) if scheduled_post else None,
    )


async def give_feedback(
    db: AsyncSession,
    llm: LLM,
    user: User,
    post_id: str,
    feedback: str,
    format: Optional[Format],
    now: datetime,
) -> VersionResponse:
    """
    Write the Post's next Version from Feedback, once its Scheduled post shows it takes Feedback:
    only a Draft or a Failed Post does.
    """
    await version_writing.user_post(db, user=user, post_id=post_id)
    scheduled_post = await service.get_for_post(db, post_id=post_id)
    check_takes_feedback(post_status(scheduled_post.state if scheduled_post else None))
    return await version_writing.add_version(
        db, llm, user=user, post_id=post_id, feedback=feedback, format=format, now=now
    )


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
