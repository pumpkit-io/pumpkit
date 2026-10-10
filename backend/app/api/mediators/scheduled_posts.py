from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.scheduled_posts as scheduled_posts_service
import app.api.services.x_connections as x_connections_service
from app.core.datetimes import as_utc
from app.core.x_publisher import XPublisher
from app.db.models import ScheduledPost, User, XConnection
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


async def create_scheduled_post(
    db: AsyncSession,
    publisher: XPublisher,
    user: User,
    text: str,
    publish_at: Optional[datetime],
    now: datetime,
) -> ScheduledPostResponse:
    """
    A Scheduled post on the User's X connection: for `publish_at`, left for the publisher, or
    when that is None, published within the request and returned Published or Failed.
    """
    connection = await connection_to_publish_on(db, user_id=user.id)
    check_length(text)
    if publish_at is None:
        return await _post_now(db, publisher, user, connection, text, now)

    scheduled_post = await scheduled_posts_service.create(
        db,
        user_id=user.id,
        x_user_id=connection.x_user_id,
        text=text,
        publish_at=check_publish_at(publish_at, now=now),
        now=now,
    )
    await db.commit()
    return scheduled_post_response(scheduled_post)


async def _post_now(
    db: AsyncSession,
    publisher: XPublisher,
    user: User,
    connection: XConnection,
    text: str,
    now: datetime,
) -> ScheduledPostResponse:
    scheduled_post = await scheduled_posts_service.create(
        db,
        user_id=user.id,
        x_user_id=connection.x_user_id,
        text=text,
        publish_at=now.replace(second=0, microsecond=0),
        now=now,
    )
    scheduled_post_id = scheduled_post.id
    # Publishing owns the transaction from here: it commits the new row along with its claim.
    await publish_scheduled_post(db, publisher, scheduled_post_id=scheduled_post_id, now=now)
    published = await scheduled_posts_service.get(db, scheduled_post_id=scheduled_post_id)
    assert published is not None
    return scheduled_post_response(published)
