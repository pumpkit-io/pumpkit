"""
Scheduled posts and their moves between states.
Flushes and never commits: the mediator or the publishing module owns the transaction.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, cast

from sqlalchemy import CursorResult, case, delete, func, or_, select, update
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


@dataclass(frozen=True)
class Reschedule:
    publish_at: datetime
    x_user_id: str


async def edit(
    db: AsyncSession,
    *,
    scheduled_post_id: str,
    text: Optional[str],
    reschedule: Optional[Reschedule],
    now: datetime,
) -> bool:
    """
    Change a scheduled or Failed Scheduled post; False if it was in neither. Rescheduling puts it
    back in scheduled for the new time and X account, as if it had never been tried. The state
    check in the update keeps a claim by the publisher between the User's read and this write safe.
    """
    values: dict[str, object] = {"updated_at": now}
    if text is not None:
        values["text"] = text
    if reschedule is not None:
        values.update(
            state=SCHEDULED,
            publish_at=reschedule.publish_at,
            x_user_id=reschedule.x_user_id,
            failed_reason=None,
            retry_count=0,
            next_attempt_at=None,
            publishing_started_at=None,
        )
    result = await db.execute(
        update(ScheduledPost)
        .where(
            ScheduledPost.id == scheduled_post_id,
            ScheduledPost.state.in_([SCHEDULED, FAILED]),
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult, result).rowcount == 1


async def cancel(db: AsyncSession, *, scheduled_post_id: str) -> bool:
    """Delete a Scheduled post still in scheduled; False if it wasn't, like a claim's check."""
    result = await db.execute(
        delete(ScheduledPost)
        .where(ScheduledPost.id == scheduled_post_id, ScheduledPost.state == SCHEDULED)
        .execution_options(synchronize_session=False)
    )
    return cast(CursorResult, result).rowcount == 1


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


async def claim_next_due(db: AsyncSession, *, now: datetime) -> Optional[str]:
    """
    Move the soonest due Scheduled post from scheduled to publishing and return its id; None
    when nothing is due. Concurrent callers skip each other's rows on Postgres, and the state
    check in the update keeps a claim single on databases without row locks.
    """
    due = (
        select(ScheduledPost.id)
        .where(
            ScheduledPost.state == SCHEDULED,
            ScheduledPost.publish_at <= now,
            or_(ScheduledPost.next_attempt_at.is_(None), ScheduledPost.next_attempt_at <= now),
        )
        .order_by(ScheduledPost.publish_at, ScheduledPost.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    result = await db.execute(
        update(ScheduledPost)
        .where(ScheduledPost.id == due, ScheduledPost.state == SCHEDULED)
        .values(state=PUBLISHING, publishing_started_at=now, updated_at=now)
        .returning(ScheduledPost.id)
        .execution_options(synchronize_session=False)
    )
    return result.scalar_one_or_none()


async def fail_stuck(
    db: AsyncSession, *, publishing_since: datetime, reason: str, now: datetime
) -> list[str]:
    """
    Move every Scheduled post in publishing since before `publishing_since` to Failed, and
    return their Users' ids, one per Scheduled post.
    """
    result = await db.execute(
        update(ScheduledPost)
        .where(
            ScheduledPost.state == PUBLISHING,
            ScheduledPost.publishing_started_at < publishing_since,
        )
        .values(state=FAILED, failed_reason=reason, updated_at=now)
        .returning(ScheduledPost.user_id)
        .execution_options(synchronize_session=False)
    )
    return list(result.scalars())


async def count_waiting(db: AsyncSession, *, user_id: str, x_user_id: str) -> int:
    """The User's Scheduled posts still in scheduled for the X account."""
    result = await db.execute(
        select(func.count())
        .select_from(ScheduledPost)
        .where(
            ScheduledPost.user_id == user_id,
            ScheduledPost.x_user_id == x_user_id,
            ScheduledPost.state == SCHEDULED,
        )
    )
    return result.scalar_one()


async def count_publishing_between(
    db: AsyncSession,
    *,
    user_id: str,
    start: datetime,
    end: datetime,
    excluding_id: Optional[str] = None,
) -> int:
    """The User's Scheduled posts in any state with `start <= publish_at < end`."""
    query = (
        select(func.count())
        .select_from(ScheduledPost)
        .where(
            ScheduledPost.user_id == user_id,
            ScheduledPost.publish_at >= start,
            ScheduledPost.publish_at < end,
        )
    )
    if excluding_id is not None:
        query = query.where(ScheduledPost.id != excluding_id)
    result = await db.execute(query)
    return result.scalar_one()


async def release_for_retry(
    db: AsyncSession, scheduled_post: ScheduledPost, *, next_attempt_at: datetime, now: datetime
) -> None:
    """Back from publishing to scheduled, due again at `next_attempt_at`. Flushes."""
    scheduled_post.state = SCHEDULED
    scheduled_post.retry_count += 1
    scheduled_post.next_attempt_at = next_attempt_at
    scheduled_post.publishing_started_at = None
    scheduled_post.updated_at = now
    await db.flush()


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
