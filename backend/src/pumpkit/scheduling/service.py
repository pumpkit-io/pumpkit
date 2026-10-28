"""
Scheduled posts and their moves between states.
Flushes and never commits: the caller (the mediator or `publishing`) owns the transaction.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, cast

from sqlalchemy import (
    ColumnElement,
    CursorResult,
    Exists,
    and_,
    case,
    delete,
    func,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.scheduling.communities import Community, Destination
from pumpkit.scheduling.models import (
    FAILED,
    PUBLISHED,
    PUBLISHING,
    SCHEDULED,
    ScheduledPost,
    ScheduledPostPart,
    ScheduledPostState,
)


async def create(
    db: AsyncSession,
    *,
    user_id: str,
    x_user_id: str,
    post_id: str,
    source_version_id: str,
    parts: list[str],
    publish_at: datetime,
    now: datetime,
    destination: Destination = Destination(),
) -> ScheduledPost:
    """
    A new Scheduled post in scheduled, copied from the Version `source_version_id` of the Post
    `post_id`. Flushes, raising IntegrityError when the Post already has one.
    """
    scheduled_post = ScheduledPost(
        user_id=user_id,
        x_user_id=x_user_id,
        parts=_parts(parts),
        **_destination_columns(destination),
        community_set_at=now if destination.community else None,
        publish_at=publish_at,
        post_id=post_id,
        source_version_id=source_version_id,
        state=SCHEDULED,
        retry_count=0,
        created_at=now,
        updated_at=now,
    )
    db.add(scheduled_post)
    await db.flush()
    return scheduled_post


def _parts(parts: list[str]) -> list[ScheduledPostPart]:
    return [ScheduledPostPart(position=position, text=text) for position, text in enumerate(parts)]


def _destination_columns(destination: Destination) -> dict[str, Any]:
    community = destination.community
    return {
        "community_id": community.id if community else None,
        "community_name": community.name if community else None,
        "share_with_followers": community is not None and destination.share_with_followers,
    }


async def list_for_user(
    db: AsyncSession, *, user_id: str, state: Optional[ScheduledPostState] = None
) -> list[ScheduledPost]:
    """Waiting ones first, soonest first; then Published and Failed ones, newest first."""
    waiting = ScheduledPost.state.in_([SCHEDULED, PUBLISHING])
    query = select(ScheduledPost).where(ScheduledPost.user_id == user_id)
    if state is not None:
        query = query.where(ScheduledPost.state == state)
    result = await db.execute(
        query.order_by(
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


async def get_for_post(db: AsyncSession, *, post_id: str) -> Optional[ScheduledPost]:
    """The Post's Scheduled post in any state, or None while it is a Draft."""
    result = await db.execute(
        select(ScheduledPost)
        .where(ScheduledPost.post_id == post_id)
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
    parts: Optional[list[str]],
    reschedule: Optional[Reschedule],
    now: datetime,
    destination: Optional[Destination] = None,
) -> bool:
    """
    Change a scheduled or Failed Scheduled post; False if it was in neither. Rescheduling puts it
    back in scheduled for the new time and X account, as if it had never been tried. The state
    check in the update keeps a claim by the publisher between the User's read and this write safe.
    A `destination` of None leaves it where it goes; moving it into another Community is a use.
    New `parts` replace every Part not live; the live ones, which open the list, stay as they
    are with their X post ids.
    """
    values: dict[str, object] = {"updated_at": now}
    if destination is not None:
        community = destination.community
        values.update(_destination_columns(destination))
        values["community_set_at"] = (
            case(
                (ScheduledPost.community_id.is_distinct_from(community.id), now),
                else_=ScheduledPost.community_set_at,
            )
            if community
            else None
        )
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
    if cast(CursorResult, result).rowcount != 1:
        return False
    if parts is not None:
        await db.execute(
            delete(ScheduledPostPart).where(
                ScheduledPostPart.scheduled_post_id == scheduled_post_id,
                ScheduledPostPart.x_post_id.is_(None),
            )
        )
        live_count = (
            await db.execute(
                select(func.count())
                .select_from(ScheduledPostPart)
                .where(ScheduledPostPart.scheduled_post_id == scheduled_post_id)
            )
        ).scalar_one()
        new_parts = [
            {"scheduled_post_id": scheduled_post_id, "position": position, "text": text}
            for position, text in enumerate(parts)
            if position >= live_count
        ]
        if new_parts:
            await db.execute(insert(ScheduledPostPart), new_parts)
    return True


async def cancel(db: AsyncSession, *, scheduled_post_id: str) -> bool:
    """Delete a scheduled or Failed Scheduled post; False if it was in neither, like a claim's check."""
    result = await db.execute(
        delete(ScheduledPost)
        .where(
            ScheduledPost.id == scheduled_post_id,
            ScheduledPost.state.in_([SCHEDULED, FAILED]),
        )
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


async def publish_stuck(
    db: AsyncSession, *, publishing_since: datetime, now: datetime
) -> list[str]:
    """
    Move every Scheduled post in publishing since before `publishing_since` whose Parts are all
    live to Published, at its claim time, and return their ids.
    """
    result = await db.execute(
        update(ScheduledPost)
        .where(_stuck(publishing_since), ~_has_part_not_live())
        .values(
            state=PUBLISHED,
            published_at=ScheduledPost.publishing_started_at,
            updated_at=now,
        )
        .returning(ScheduledPost.id)
        .execution_options(synchronize_session=False)
    )
    return list(result.scalars())


async def fail_stuck(
    db: AsyncSession, *, publishing_since: datetime, reason: str, now: datetime
) -> list[str]:
    """
    Move every Scheduled post in publishing since before `publishing_since` with a Part not
    live to Failed, and return their ids. Parts already live stay live.
    """
    result = await db.execute(
        update(ScheduledPost)
        .where(_stuck(publishing_since), _has_part_not_live())
        .values(state=FAILED, failed_reason=reason, updated_at=now)
        .returning(ScheduledPost.id)
        .execution_options(synchronize_session=False)
    )
    return list(result.scalars())


def _stuck(publishing_since: datetime) -> ColumnElement[bool]:
    return and_(
        ScheduledPost.state == PUBLISHING,
        ScheduledPost.publishing_started_at < publishing_since,
    )


def _has_part_not_live() -> Exists:
    return (
        select(ScheduledPostPart.id)
        .where(
            ScheduledPostPart.scheduled_post_id == ScheduledPost.id,
            ScheduledPostPart.x_post_id.is_(None),
        )
        .exists()
    )


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


async def past_communities(db: AsyncSession, *, user_id: str, x_user_id: str) -> list[Community]:
    """
    The Communities of the User's Scheduled posts for the X account, the one most recently set
    on a Scheduled post first, each once under the latest name stored for it.
    """
    result = await db.execute(
        select(ScheduledPost.community_id, ScheduledPost.community_name)
        .where(
            ScheduledPost.user_id == user_id,
            ScheduledPost.x_user_id == x_user_id,
            ScheduledPost.community_id.is_not(None),
        )
        .order_by(ScheduledPost.community_set_at.desc(), ScheduledPost.id.desc())
    )
    names: dict[str, Optional[str]] = {}
    for community_id, name in result.tuples():
        if community_id is not None and names.get(community_id) is None:
            names[community_id] = name
    return [Community(id=community_id, name=name) for community_id, name in names.items()]


async def count_x_posts_between(
    db: AsyncSession,
    *,
    user_id: str,
    start: datetime,
    end: datetime,
    excluding_id: Optional[str] = None,
) -> int:
    """The Parts of the User's Scheduled posts in any state with `start <= publish_at < end`."""
    query = (
        select(func.count())
        .select_from(ScheduledPostPart)
        .join(ScheduledPost)
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


async def record_part_live(db: AsyncSession, part: ScheduledPostPart, *, x_post_id: str) -> None:
    """The Part is live as X's post `x_post_id`. Flushes."""
    part.x_post_id = x_post_id
    await db.flush()


async def record_published(
    db: AsyncSession, scheduled_post: ScheduledPost, *, now: datetime
) -> None:
    """Every Part is live, the last one accepted at `now`. Flushes."""
    scheduled_post.state = PUBLISHED
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
