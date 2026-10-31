"""
What Scheduled posts take from Top-ups (ADR 0017): the X posts and link posts their Allowance
period can't cover, charged to the Top-ups still unexpired at each one's publish time.
"""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.billing.service as billing_service
from pumpkit.billing.allowance import Allowance
from pumpkit.billing.models import AllowanceCount
from pumpkit.core.time import as_utc
from pumpkit.scheduling import service
from pumpkit.scheduling.models import ScheduledPost
from pumpkit.scheduling.rules import x_posts_in

_COUNTS: tuple[AllowanceCount, ...] = ("x_posts", "link_x_posts")


async def rebalance_top_ups(db: AsyncSession, *, user_id: str, moments: Iterable[datetime]) -> None:
    """
    Charge the User's waiting and Failed Scheduled posts afresh in the Allowance periods holding
    `moments`, after one there is created, changed, deleted or Failed. Their charges go back to
    the Top-ups, then each, in publish-time order, takes what its period can't cover, so the
    Top-ups pay exactly for the overflow. Call it with the User locked. Flushes.
    """
    allowances: dict[datetime, Allowance] = {}
    for moment in moments:
        allowance = await billing_service.get_allowance(db, user_id=user_id, moment=moment)
        if allowance is not None:
            allowances[allowance.period.start] = allowance
    changeable = {
        start: await service.changeable_between(
            db, user_id=user_id, start=start, end=allowance.period.end
        )
        for start, allowance in allowances.items()
    }
    # Every charge goes back before any is made, so a post leaving a period frees its Top-ups.
    for scheduled_posts in changeable.values():
        for scheduled_post in scheduled_posts:
            await billing_service.give_back_charges(db, scheduled_post_id=scheduled_post.id)
    for start in sorted(allowances):
        await _charge_in_order(db, allowances[start], changeable[start], user_id=user_id)


async def _charge_in_order(
    db: AsyncSession, allowance: Allowance, scheduled_posts: list[ScheduledPost], *, user_id: str
) -> None:
    period = allowance.period
    used = await service.x_posts_used_between(
        db, user_id=user_id, start=period.start, end=period.end
    )
    needs = [
        x_posts_in(await service.counted_parts(db, scheduled_post_id=scheduled_post.id))
        for scheduled_post in scheduled_posts
    ]
    # What the period's other Scheduled posts, those that can no longer change, use of it.
    before = {
        count: getattr(used, count) - sum(getattr(needed, count) for needed in needs)
        for count in _COUNTS
    }
    for scheduled_post, needed in zip(scheduled_posts, needs):
        for count in _COUNTS:
            charged = await billing_service.charge_shortfall(
                db,
                user_id=user_id,
                allowance=allowance,
                count=count,
                used=before[count],
                needed=getattr(needed, count),
                moment=as_utc(scheduled_post.publish_at),
                scheduled_post_id=scheduled_post.id,
            )
            before[count] += getattr(needed, count) - charged
