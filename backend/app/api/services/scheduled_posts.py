"""
Scheduled posts and their moves between states.
Flushes and never commits: the mediator or the publishing module owns the transaction.
"""

from datetime import datetime
from typing import Optional, cast

from sqlalchemy import CursorResult, case, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import FAILED, PUBLISHED, PUBLISHING, SCHEDULED, ScheduledPost


async def create(
    db: AsyncSession,
    *,
    user_id: str,
    x_user_id: str,
    text: str,
    publish_at: datetime,
    now: datetime,
) -> ScheduledPost:
    """A new Scheduled post in scheduled. Flushes."""
    scheduled_post = ScheduledPost(
        user_id=user_id,
        x_user_id=x_user_id,
        text=text,
        publish_at=publish_at,
        state=SCHEDULED,
        retry_count=0,
        created_at=now,
        updated_at=now,
    )
    db.add(scheduled_post)
    await db.flush()
    return scheduled_post


async def list_for_user(db: AsyncSession, *, user_id: str) -> list[ScheduledPost]:
    """Waiting ones first, soonest first; then Published and Failed ones, newest first."""
    waiting = ScheduledPost.state.in_([SCHEDULED, PUBLISHING])
    result = await db.execute(
        select(ScheduledPost)
        .where(ScheduledPost.user_id == user_id)
        .order_by(
            case((waiting, 0), else_=1),
            case((waiting, ScheduledPost.publish_at)),
            ScheduledPost.publish_at.desc(),
            ScheduledPost.created_at.desc(),
            ScheduledPost.id.desc(),
        )
    )
    return list(result.scalars())


async def get(db: AsyncSession, *, scheduled_post_id: str) -> Optional[ScheduledPost]:
    """Reloaded from the database, since claims change rows behind the session's back."""
    result = await db.execute(
        select(ScheduledPost)
        .where(ScheduledPost.id == scheduled_post_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def claim(db: AsyncSession, *, scheduled_post_id: str, now: datetime) -> bool:
    """
    Move the Scheduled post from scheduled to publishing; False if it wasn't scheduled. The
    conditional update decides, so of two concurrent claims, on any database, one wins.
    """
    result = await db.execute(
        update(ScheduledPost)
        .where(ScheduledPost.id == scheduled_post_id, ScheduledPost.state == SCHEDULED)
        .values(state=PUBLISHING, publishing_started_at=now, updated_at=now)
    )
    return cast(CursorResult, result).rowcount == 1


async def record_published(
    db: AsyncSession, scheduled_post: ScheduledPost, *, x_post_id: str, now: datetime
) -> None:
    """Flushes."""
    scheduled_post.state = PUBLISHED
    scheduled_post.x_post_id = x_post_id
    scheduled_post.published_at = now
    scheduled_post.updated_at = now
    await db.flush()


async def record_failed(
    db: AsyncSession, scheduled_post: ScheduledPost, *, reason: str, now: datetime
) -> None:
    """Flushes."""
    scheduled_post.state = FAILED
    scheduled_post.failed_reason = reason
    scheduled_post.updated_at = now
    await db.flush()
