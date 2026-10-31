"""
Scheduled posts and their moves between states.
Flushes and never commits: the caller (the mediator or `publishing`) owns the transaction.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, cast

from sqlalchemy import (
    ColumnElement,
    CursorResult,
    Exists,
    Select,
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
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import Subquery

from pumpkit.billing.models import TopUpCharge
from pumpkit.posts.models import ATTEMPT_SUCCEEDED, Post, VersionAttempt
from pumpkit.scheduling.communities import Community, Destination
from pumpkit.scheduling.models import (
    FAILED,
    PUBLISHED,
    PUBLISHING,
    SCHEDULED,
    ScheduledPost,
    ScheduledPostPart,
    UnscheduledLiveParts,
)
from pumpkit.scheduling.post_status import (
    DRAFT,
    FAILED_STATUS,
    PUBLISHED_STATUS,
    SCHEDULED_STATUS,
    STATUS_OF_STATE,
    PostStatus,
)
from pumpkit.scheduling.rules import XPosts, x_posts_in


async def create(
    db: AsyncSession,
    *,
    user_id: str,
    x_user_id: str,
    post_id: str,
    parts: list[str],
    publish_at: datetime,
    now: datetime,
    destination: Destination = Destination(),
) -> ScheduledPost:
    """
    A new Scheduled post in scheduled, copied from the Text of the Post `post_id`. Flushes,
    raising IntegrityError when the Post already has one.
    """
    scheduled_post = ScheduledPost(
        user_id=user_id,
        x_user_id=x_user_id,
        parts=_parts(parts),
        **_destination_columns(destination),
        community_set_at=now if destination.community else None,
        publish_at=publish_at,
        post_id=post_id,
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


def _post_status_column() -> ColumnElement[str]:
    """`post_status` in SQL, for a Post outer-joined to its Scheduled post."""
    # `case(value=...)` binds each state as VARCHAR, which Postgres won't compare with the enum.
    return case(
        *((ScheduledPost.state == state, status) for state, status in STATUS_OF_STATE.items()),
        else_=DRAFT,
    )


def _latest_versions() -> Subquery:
    """Each Post with a Version, and when its latest Version was written."""
    return (
        select(
            VersionAttempt.post_id.label("post_id"),
            func.max(VersionAttempt.created_at).label("latest_at"),
        )
        .where(VersionAttempt.status == ATTEMPT_SUCCEEDED)
        .group_by(VersionAttempt.post_id)
        .subquery()
    )


@dataclass(frozen=True)
class ListedPost:
    post: Post
    # None while the Post is a Draft.
    scheduled_post: Optional[ScheduledPost]


async def list_posts(
    db: AsyncSession, *, user_id: str, status: Optional[PostStatus], limit: int, offset: int
) -> list[ListedPost]:
    """A page of the User's Posts with a Version, in `status` or every one, in its tab's order."""
    latest = _latest_versions()
    query = (
        select(Post, ScheduledPost)
        .join(latest, latest.c.post_id == Post.id)
        .outerjoin(ScheduledPost, ScheduledPost.post_id == Post.id)
        .where(Post.user_id == user_id)
        .options(selectinload(Post.attempts))
    )
    if status is not None:
        query = query.where(_post_status_column() == status)
    # Drafts, like every Post listed together, go by their latest Version, newest first.
    if status == SCHEDULED_STATUS:
        order = [ScheduledPost.publish_at, ScheduledPost.id]
    elif status == PUBLISHED_STATUS:
        order = [ScheduledPost.published_at.desc(), ScheduledPost.id.desc()]
    elif status == FAILED_STATUS:
        order = [ScheduledPost.publish_at.desc(), ScheduledPost.id.desc()]
    else:
        order = [latest.c.latest_at.desc(), Post.id.desc()]
    result = await db.execute(query.order_by(*order).limit(limit).offset(offset))
    return [ListedPost(post=post, scheduled_post=scheduled) for post, scheduled in result.tuples()]


async def count_posts(db: AsyncSession, *, user_id: str) -> dict[PostStatus, int]:
    """How many of the User's Posts with a Version each status holds."""
    latest = _latest_versions()
    status = _post_status_column()
    result = await db.execute(
        select(status, func.count())
        .select_from(Post)
        .join(latest, latest.c.post_id == Post.id)
        .outerjoin(ScheduledPost, ScheduledPost.post_id == Post.id)
        .where(Post.user_id == user_id)
        .group_by(status)
    )
    counts: dict[PostStatus, int] = {
        DRAFT: 0,
        SCHEDULED_STATUS: 0,
        PUBLISHED_STATUS: 0,
        FAILED_STATUS: 0,
    }
    for listed_status, count in result.tuples():
        counts[cast(PostStatus, listed_status)] = count
    return counts


async def get(db: AsyncSession, *, scheduled_post_id: str) -> Optional[ScheduledPost]:
    """Reloaded from the database, since claims change rows behind the session's back."""
    result = await db.execute(_reload(scheduled_post_id))
    return result.scalar_one_or_none()


async def get_existing(db: AsyncSession, *, scheduled_post_id: str) -> ScheduledPost:
    """Reloaded like `get`, for one the caller knows exists: raises `NoResultFound` otherwise."""
    result = await db.execute(_reload(scheduled_post_id))
    return result.scalar_one()


def _reload(scheduled_post_id: str) -> Select[tuple[ScheduledPost]]:
    return (
        select(ScheduledPost)
        .where(ScheduledPost.id == scheduled_post_id)
        .execution_options(populate_existing=True)
    )


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


async def stop(db: AsyncSession, *, scheduled_post_id: str, now: datetime) -> bool:
    """
    Move a scheduled or Failed Scheduled post to Failed, so only its live Parts count; False if
    it was in neither, like a claim's check.
    """
    result = await db.execute(
        update(ScheduledPost)
        .where(
            ScheduledPost.id == scheduled_post_id,
            ScheduledPost.state.in_([SCHEDULED, FAILED]),
        )
        .values(state=FAILED, updated_at=now)
    )
    return cast(CursorResult, result).rowcount == 1


async def keep_unscheduled_live_parts(
    db: AsyncSession, *, user_id: str, publish_at: datetime, x_posts: XPosts, now: datetime
) -> None:
    """Flushes."""
    db.add(
        UnscheduledLiveParts(
            user_id=user_id,
            publish_at=publish_at,
            x_posts=x_posts.x_posts,
            link_x_posts=x_posts.link_x_posts,
            created_at=now,
        )
    )
    await db.flush()


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


async def stuck_user_ids(db: AsyncSession, *, publishing_since: datetime) -> list[str]:
    """The Users with a Scheduled post in publishing since before `publishing_since`, in id order."""
    result = await db.execute(
        select(ScheduledPost.user_id)
        .where(_stuck(publishing_since))
        .distinct()
        .order_by(ScheduledPost.user_id)
    )
    return list(result.scalars())


async def publish_stuck(
    db: AsyncSession, *, publishing_since: datetime, user_ids: list[str], now: datetime
) -> list[str]:
    """
    Move every Scheduled post of `user_ids` in publishing since before `publishing_since` whose
    Parts are all live to Published, at its claim time, and return their ids.
    """
    result = await db.execute(
        update(ScheduledPost)
        .where(_stuck(publishing_since), ScheduledPost.user_id.in_(user_ids), ~_has_part_not_live())
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
    db: AsyncSession,
    *,
    publishing_since: datetime,
    user_ids: list[str],
    reason: str,
    now: datetime,
) -> list[str]:
    """
    Move every Scheduled post of `user_ids` in publishing since before `publishing_since` with a
    Part not live to Failed, and return their ids. Parts already live stay live.
    """
    result = await db.execute(
        update(ScheduledPost)
        .where(_stuck(publishing_since), ScheduledPost.user_id.in_(user_ids), _has_part_not_live())
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


async def x_posts_used_between(
    db: AsyncSession,
    *,
    user_id: str,
    start: datetime,
    end: datetime,
    excluding: Collection[str] = (),
) -> XPosts:
    """
    The X posts and link posts of the User's Scheduled posts with `start <= publish_at < end`:
    every Part, except those of a Failed one that X never accepted, which cost nothing, less
    those charged to a Top-up, refunded or disputed since or not, plus the live Parts of deleted
    ones.
    """
    in_window = [
        ScheduledPost.user_id == user_id,
        ScheduledPost.publish_at >= start,
        ScheduledPost.publish_at < end,
    ]
    if excluding:
        in_window.append(ScheduledPost.id.not_in(excluding))
    parts = await db.execute(
        select(ScheduledPostPart.text)
        .join(ScheduledPost)
        .where(
            *in_window,
            or_(ScheduledPost.state != FAILED, ScheduledPostPart.x_post_id.is_not(None)),
        )
    )
    charged: dict[str, int] = {
        count: quantity
        for count, quantity in (
            await db.execute(
                select(TopUpCharge.count, func.sum(TopUpCharge.quantity))
                .join(ScheduledPost, TopUpCharge.scheduled_post_id == ScheduledPost.id)
                .where(*in_window)
                .group_by(TopUpCharge.count)
            )
        ).tuples()
    }
    unscheduled = (
        await db.execute(
            select(
                func.coalesce(func.sum(UnscheduledLiveParts.x_posts), 0),
                func.coalesce(func.sum(UnscheduledLiveParts.link_x_posts), 0),
            ).where(
                UnscheduledLiveParts.user_id == user_id,
                UnscheduledLiveParts.publish_at >= start,
                UnscheduledLiveParts.publish_at < end,
            )
        )
    ).one()
    counted = x_posts_in(list(parts.scalars()))
    return XPosts(
        x_posts=counted.x_posts - charged.get("x_posts", 0) + unscheduled[0],
        link_x_posts=counted.link_x_posts - charged.get("link_x_posts", 0) + unscheduled[1],
    )


async def changeable_between(
    db: AsyncSession, *, user_id: str, start: datetime, end: datetime
) -> list[ScheduledPost]:
    """
    The User's waiting and Failed Scheduled posts with `start <= publish_at < end`, the ones
    whose Parts may still change, in publish-time order.
    """
    result = await db.execute(
        select(ScheduledPost)
        .where(
            ScheduledPost.user_id == user_id,
            ScheduledPost.publish_at >= start,
            ScheduledPost.publish_at < end,
            ScheduledPost.state.in_([SCHEDULED, FAILED]),
        )
        .order_by(ScheduledPost.publish_at, ScheduledPost.created_at, ScheduledPost.id)
    )
    return list(result.scalars())


async def counted_parts(db: AsyncSession, *, scheduled_post_id: str) -> list[str]:
    """
    The Parts of the Scheduled post that count as X posts: every one, or of a Failed one only
    those X accepted.
    """
    result = await db.execute(
        select(ScheduledPostPart.text)
        .join(ScheduledPost)
        .where(
            ScheduledPost.id == scheduled_post_id,
            or_(ScheduledPost.state != FAILED, ScheduledPostPart.x_post_id.is_not(None)),
        )
        .order_by(ScheduledPostPart.position)
    )
    return list(result.scalars())


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
