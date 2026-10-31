"""
What Scheduled posts take from Top-ups (ADR 0017): the X posts and link posts their Allowance
period can't cover, charged to the Top-ups still unexpired at each one's publish time. Every
waiting and Failed one in a period is charged afresh, in publish-time order, whenever one there
changes, and a change is checked against that same charging before it is made.
"""

from bisect import bisect_right
from collections.abc import Collection, Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.billing.service as billing_service
from pumpkit.billing.allowance import Allowance, AllowanceUsedUp
from pumpkit.billing.models import AllowanceCount
from pumpkit.billing.top_ups import Covered, Need, TopUpBalance, cover_in_order
from pumpkit.core.time import as_utc
from pumpkit.scheduling import service
from pumpkit.scheduling.rules import XPosts, x_posts_in

_COUNTS: tuple[AllowanceCount, ...] = ("x_posts", "link_x_posts")


@dataclass(frozen=True)
class _Planned:
    """One waiting or Failed Scheduled post as the charging sees it; no id for one not yet made."""

    scheduled_post_id: Optional[str]
    publish_at: datetime
    needed: XPosts


@dataclass(frozen=True)
class _Period:
    allowance: Allowance
    # What the period's Scheduled posts that can no longer change use, less their charges.
    fixed: XPosts
    # In publish-time order.
    planned: list[_Planned]


def _cover(
    periods: list[_Period], balances: list[TopUpBalance], *, count: AllowanceCount
) -> list[list[Covered]]:
    """How each period's planned posts are paid for, earliest period first, sharing the Top-ups."""
    covered: list[list[Covered]] = []
    for period in sorted(periods, key=lambda p: p.allowance.period.start):
        in_period, balances = cover_in_order(
            balances,
            count=count,
            limit=getattr(period.allowance, count),
            used=getattr(period.fixed, count),
            needs=[Need(p.publish_at, getattr(p.needed, count)) for p in period.planned],
        )
        covered.append(in_period)
    return covered


async def _allowances(
    db: AsyncSession, *, user_id: str, moments: Iterable[datetime]
) -> list[Allowance]:
    """The Allowances of the periods holding `moments`, one per period, earliest first."""
    allowances: dict[datetime, Allowance] = {}
    for moment in moments:
        allowance = await billing_service.get_allowance(db, user_id=user_id, moment=moment)
        if allowance is not None:
            allowances[allowance.period.start] = allowance
    return [allowances[start] for start in sorted(allowances)]


async def _paid_on_removed(
    db: AsyncSession, *, scheduled_post_id: str, needed: XPosts, trimming: bool
) -> XPosts:
    """
    What the Scheduled post keeps from Top-ups since removed, at most what it needs now. With
    `trimming`, charges over that are cut, as when an edit or a failure shrinks it.
    """
    charged = await billing_service.charges_on_removed(db, scheduled_post_id=scheduled_post_id)
    kept: dict[AllowanceCount, int] = {}
    for count in _COUNTS:
        kept[count] = min(charged.get(count, 0), getattr(needed, count))
        if trimming and charged.get(count, 0) > kept[count]:
            await billing_service.trim_charges_on_removed(
                db, scheduled_post_id=scheduled_post_id, count=count, keep=kept[count]
            )
    return XPosts(**kept)


def _less(needed: XPosts, paid: XPosts) -> XPosts:
    return XPosts(**{count: getattr(needed, count) - getattr(paid, count) for count in _COUNTS})


async def _planned(
    db: AsyncSession,
    *,
    user_id: str,
    allowance: Allowance,
    leaving_out: Optional[str] = None,
    trimming: bool = False,
) -> list[_Planned]:
    """
    The period's waiting and Failed Scheduled posts, each needing what it doesn't already keep
    from a removed Top-up.
    """
    period = allowance.period
    planned: list[_Planned] = []
    for scheduled_post in await service.changeable_between(
        db, user_id=user_id, start=period.start, end=period.end
    ):
        if scheduled_post.id == leaving_out:
            continue
        needed = x_posts_in(await service.counted_parts(db, scheduled_post_id=scheduled_post.id))
        paid = await _paid_on_removed(
            db, scheduled_post_id=scheduled_post.id, needed=needed, trimming=trimming
        )
        planned.append(
            _Planned(
                scheduled_post_id=scheduled_post.id,
                publish_at=as_utc(scheduled_post.publish_at),
                needed=_less(needed, paid),
            )
        )
    return planned


async def _fixed(
    db: AsyncSession, *, user_id: str, allowance: Allowance, excluding: Collection[str]
) -> XPosts:
    period = allowance.period
    return await service.x_posts_used_between(
        db, user_id=user_id, start=period.start, end=period.end, excluding=excluding
    )


async def rebalance_top_ups(db: AsyncSession, *, user_id: str, moments: Iterable[datetime]) -> None:
    """
    Charge the User's waiting and Failed Scheduled posts afresh in the Allowance periods holding
    `moments`, after one there is created, changed, deleted or Failed. Their charges go back to
    the Top-ups, then each, in publish-time order, takes what its period can't cover, so the
    Top-ups pay exactly for the overflow. Call it with the User locked. Flushes.
    """
    allowances = await _allowances(db, user_id=user_id, moments=moments)
    if not allowances:
        return
    planned = [await _planned(db, user_id=user_id, allowance=a, trimming=True) for a in allowances]
    ids = [p.scheduled_post_id for posts in planned for p in posts if p.scheduled_post_id]
    # Every charge goes back before any is made, so a post leaving a period frees its Top-ups.
    for scheduled_post_id in ids:
        await billing_service.give_back_charges(
            db, scheduled_post_id=scheduled_post_id, keeping_removed=True
        )
    periods = [
        _Period(
            allowance=allowance,
            fixed=await _fixed(db, user_id=user_id, allowance=allowance, excluding=ids),
            planned=posts,
        )
        for allowance, posts in zip(allowances, planned)
    ]
    balances = await billing_service.top_up_balances(
        db, user_id=user_id, moment=allowances[0].period.start
    )
    for count in _COUNTS:
        for period, covered in zip(periods, _cover(periods, balances, count=count)):
            for scheduled_post, paid in zip(period.planned, covered):
                if paid.charges and scheduled_post.scheduled_post_id is not None:
                    await billing_service.record_charges(
                        db,
                        scheduled_post_id=scheduled_post.scheduled_post_id,
                        count=count,
                        charges=paid.charges,
                    )


async def check_room(
    db: AsyncSession,
    *,
    user_id: str,
    allowance: Allowance,
    publish_at: datetime,
    needed: XPosts,
    counts: list[AllowanceCount],
    changing_id: Optional[str] = None,
) -> None:
    """
    Raise `AllowanceUsedUp` unless charging the period afresh with a Scheduled post needing
    `needed` at `publish_at` leaves every post there covered, by the Allowance or by Top-ups
    unexpired at its own publish time, for each of `counts`. A post earlier in the period can push
    a later one onto a Top-up that has expired by then. Pass `changing_id` when changing an
    existing one, which leaves its old place and keeps what a removed Top-up paid for. Call it
    with the User locked.
    """
    moments = [publish_at]
    paid = XPosts(x_posts=0, link_x_posts=0)
    if changing_id is not None:
        changing = await service.get(db, scheduled_post_id=changing_id)
        assert changing is not None
        moments.append(as_utc(changing.publish_at))
        paid = await _paid_on_removed(
            db, scheduled_post_id=changing_id, needed=needed, trimming=False
        )
    allowances = await _allowances(db, user_id=user_id, moments=moments)
    planned = [
        await _planned(db, user_id=user_id, allowance=a, leaving_out=changing_id)
        for a in allowances
    ]
    ids = {p.scheduled_post_id for posts in planned for p in posts if p.scheduled_post_id}
    if changing_id is not None:
        ids.add(changing_id)
    target = next(i for i, a in enumerate(allowances) if a.period.start == allowance.period.start)
    fixed = [await _fixed(db, user_id=user_id, allowance=a, excluding=ids) for a in allowances]
    balances = await billing_service.top_up_balances(
        db, user_id=user_id, moment=allowances[0].period.start, giving_back=ids
    )

    def uncovered(count: AllowanceCount, quantity: int) -> bool:
        new = _Planned(
            scheduled_post_id=None,
            publish_at=publish_at,
            needed=replace(needed, **{count: max(0, quantity - getattr(paid, count))}),
        )
        posts = list(planned[target])
        posts.insert(bisect_right([p.publish_at for p in posts], publish_at), new)
        periods = [
            _Period(allowance=a, fixed=f, planned=posts if i == target else planned[i])
            for i, (a, f) in enumerate(zip(allowances, fixed))
        ]
        return any(paid.uncovered for paid in _cover(periods, balances, count=count)[target])

    for count in counts:
        quantity: int = getattr(needed, count)
        if not uncovered(count, quantity):
            continue
        left = next((k for k in range(quantity - 1, -1, -1) if not uncovered(count, k)), 0)
        limit = getattr(allowance, count)
        assert limit is not None
        raise AllowanceUsedUp(
            ran_out=count, needed=quantity, left=left, limit=limit, allowance=allowance
        )
