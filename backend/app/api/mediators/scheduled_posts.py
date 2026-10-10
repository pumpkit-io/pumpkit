from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.posts as posts_service
import app.api.services.scheduled_posts as scheduled_posts_service
import app.api.services.x_connections as x_connections_service
from app.core.config import settings
from app.core.datetimes import as_utc
from app.core.x_publisher import XPublisher
from app.db.models import FAILED, SCHEDULED, ScheduledPost, User, XConnection
from app.publishing.publish import publish_scheduled_post
from app.publishing.x_length import X_POST_MAX_CHARS, x_weighted_length
from app.schemas.scheduled_posts import ScheduledPostResponse, ScheduledPostsListResponse


def scheduled_post_response(scheduled_post: ScheduledPost) -> ScheduledPostResponse:
    published_at = scheduled_post.published_at
    x_post_id = scheduled_post.x_post_id
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
        created_at=as_utc(scheduled_post.created_at),
    )


async def list_scheduled_posts(db: AsyncSession, user: User) -> ScheduledPostsListResponse:
    scheduled_posts = await scheduled_posts_service.list_for_user(db, user_id=user.id)
    return ScheduledPostsListResponse(data=[scheduled_post_response(s) for s in scheduled_posts])


# A publish time is at least this far ahead, so the User can't schedule one by mistake for now.
MIN_LEAD_TIME = timedelta(minutes=1)
MAX_LEAD_TIME = timedelta(days=365)


async def connection_to_publish_on(db: AsyncSession, *, user_id: str) -> XConnection:
    """The X connection a new or rescheduled Scheduled post targets, or a 409."""
    connection = await x_connections_service.get_connection(db, user_id=user_id)
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connect your X account first.",
        )
    if connection.needs_reconnect:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="X no longer accepts Pumpkit's access to your account. Reconnect X first.",
        )
    return connection


def check_length(text: str) -> None:
    """A 422 unless X would take the text, by X's own count."""
    length = x_weighted_length(text)
    if length > X_POST_MAX_CHARS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"This post is {length} characters by X's count, over the {X_POST_MAX_CHARS} limit."
            ),
        )


def check_publish_at(publish_at: datetime, *, now: datetime) -> datetime:
    """The publish time in UTC, or a 422 unless it is a whole minute within the window."""
    publish_at = publish_at.astimezone(timezone.utc)
    if publish_at.second or publish_at.microsecond:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Pick a time on a whole minute.",
        )
    if publish_at - now < MIN_LEAD_TIME:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Pick a time at least a minute from now.",
        )
    if publish_at - now > MAX_LEAD_TIME:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Pick a time within a year from now.",
        )
    return publish_at


def _month_bounds(moment: datetime) -> tuple[datetime, datetime]:
    """The start of the UTC calendar month holding `moment`, and the start of the next one."""
    start = moment.astimezone(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    if start.month == 12:
        return start, start.replace(year=start.year + 1, month=1)
    return start, start.replace(month=start.month + 1)


async def check_monthly_cap(
    db: AsyncSession,
    *,
    user_id: str,
    publish_at: datetime,
    excluding_id: Optional[str] = None,
) -> None:
    """
    A 409 with the reset date when the User's Scheduled posts in the UTC month of `publish_at`
    are at the cap. Pass `excluding_id` when moving an existing one, so it doesn't count itself.
    """
    start, end = _month_bounds(publish_at)
    cap = settings.SCHEDULED_POSTS_MONTHLY_CAP
    count = await scheduled_posts_service.count_publishing_between(
        db, user_id=user_id, start=start, end=end, excluding_id=excluding_id
    )
    if count >= cap:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"You have {cap} Scheduled posts in {start:%B %Y}, the most for one month. "
                f"The cap resets on {end:%B} {end.day}, {end.year}."
            ),
        )


async def create_scheduled_post(
    db: AsyncSession,
    publisher: XPublisher,
    user: User,
    text: str,
    publish_at: Optional[datetime],
    now: datetime,
    source_version_id: Optional[str] = None,
) -> ScheduledPostResponse:
    """
    A Scheduled post on the User's X connection: for `publish_at`, left for the publisher, or
    when that is None, published within the request and returned Published or Failed.
    """
    connection = await connection_to_publish_on(db, user_id=user.id)
    check_length(text)
    if source_version_id is not None:
        await _check_source_version(db, user_id=user.id, version_id=source_version_id)
    if publish_at is None:
        await check_monthly_cap(db, user_id=user.id, publish_at=now)
        return await _post_now(db, publisher, user, connection, text, now, source_version_id)

    publish_at = check_publish_at(publish_at, now=now)
    await check_monthly_cap(db, user_id=user.id, publish_at=publish_at)
    scheduled_post = await scheduled_posts_service.create(
        db,
        user_id=user.id,
        x_user_id=connection.x_user_id,
        text=text,
        publish_at=publish_at,
        now=now,
        source_version_id=source_version_id,
    )
    await db.commit()
    return scheduled_post_response(scheduled_post)


async def _check_source_version(db: AsyncSession, *, user_id: str, version_id: str) -> None:
    """A 404 unless the source Version is one of the User's."""
    version = await posts_service.get_user_version(db, user_id=user_id, version_id=version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found.")


async def _post_now(
    db: AsyncSession,
    publisher: XPublisher,
    user: User,
    connection: XConnection,
    text: str,
    now: datetime,
    source_version_id: Optional[str],
) -> ScheduledPostResponse:
    scheduled_post = await scheduled_posts_service.create(
        db,
        user_id=user.id,
        x_user_id=connection.x_user_id,
        text=text,
        publish_at=now.replace(second=0, microsecond=0),
        now=now,
        source_version_id=source_version_id,
    )
    scheduled_post_id = scheduled_post.id
    # Publishing owns the transaction from here: it commits the new row along with its claim.
    await publish_scheduled_post(db, publisher, scheduled_post_id=scheduled_post_id, now=now)
    published = await scheduled_posts_service.get(db, scheduled_post_id=scheduled_post_id)
    assert published is not None
    return scheduled_post_response(published)


async def _owned(db: AsyncSession, *, user: User, scheduled_post_id: str) -> ScheduledPost:
    scheduled_post = await scheduled_posts_service.get(db, scheduled_post_id=scheduled_post_id)
    if scheduled_post is None or scheduled_post.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Scheduled post not found."
        )
    return scheduled_post


def _publishing_started() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Publishing has started, so this Scheduled post can no longer change.",
    )


async def edit_scheduled_post(
    db: AsyncSession,
    user: User,
    scheduled_post_id: str,
    text: Optional[str],
    publish_at: Optional[datetime],
    now: datetime,
) -> ScheduledPostResponse:
    """
    New text, a new publish time, or both, for a scheduled or Failed Scheduled post. A new time
    reschedules it on the X account connected now, so a Failed one gets another try.
    """
    scheduled_post = await _owned(db, user=user, scheduled_post_id=scheduled_post_id)
    if scheduled_post.state not in (SCHEDULED, FAILED):
        raise _publishing_started()
    if text is not None:
        check_length(text)
    reschedule = None
    if publish_at is not None:
        connection = await connection_to_publish_on(db, user_id=user.id)
        new_publish_at = check_publish_at(publish_at, now=now)
        await check_monthly_cap(
            db, user_id=user.id, publish_at=new_publish_at, excluding_id=scheduled_post_id
        )
        reschedule = scheduled_posts_service.Reschedule(
            publish_at=new_publish_at, x_user_id=connection.x_user_id
        )
    if not await scheduled_posts_service.edit(
        db, scheduled_post_id=scheduled_post_id, text=text, reschedule=reschedule, now=now
    ):
        raise _publishing_started()
    await db.commit()
    return scheduled_post_response(await _owned(db, user=user, scheduled_post_id=scheduled_post_id))


async def cancel_scheduled_post(db: AsyncSession, user: User, scheduled_post_id: str) -> None:
    """Delete a Scheduled post still waiting. A Failed one stays, to be rescheduled or kept."""
    scheduled_post = await _owned(db, user=user, scheduled_post_id=scheduled_post_id)
    if scheduled_post.state == FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a Scheduled post still waiting can be cancelled.",
        )
    if not await scheduled_posts_service.cancel(db, scheduled_post_id=scheduled_post_id):
        raise _publishing_started()
    await db.commit()
