"""
What a Scheduled post takes from Top-ups (ADR 0017): the X posts and link posts its Allowance
period can't cover, charged to the Top-ups still unexpired at its publish time.
"""

from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.billing.service as billing_service
from pumpkit.billing.models import AllowanceCount
from pumpkit.core.time import as_utc
from pumpkit.scheduling import service
from pumpkit.scheduling.rules import x_posts_in

_COUNTS: tuple[AllowanceCount, ...] = ("x_posts", "link_x_posts")


async def charge_top_ups(db: AsyncSession, *, scheduled_post_id: str) -> None:
    """
    Charge the Scheduled post afresh, after it is created, changed or Failed: its old charges go
    back to their Top-ups, then what its period can't cover of the Parts that count is charged
    again, first to expire first. Flushes.
    """
    await billing_service.give_back_charges(db, scheduled_post_id=scheduled_post_id)
    scheduled_post = await service.get(db, scheduled_post_id=scheduled_post_id)
    assert scheduled_post is not None
    publish_at = as_utc(scheduled_post.publish_at)
    allowance = await billing_service.get_allowance(
        db, user_id=scheduled_post.user_id, moment=publish_at
    )
    if allowance is None:
        return
    used = await service.x_posts_used_between(
        db,
        user_id=scheduled_post.user_id,
        start=allowance.period.start,
        end=allowance.period.end,
        excluding_id=scheduled_post_id,
    )
    needed = x_posts_in(await service.counted_parts(db, scheduled_post_id=scheduled_post_id))
    for count in _COUNTS:
        await billing_service.charge_shortfall(
            db,
            user_id=scheduled_post.user_id,
            allowance=allowance,
            count=count,
            used=getattr(used, count),
            needed=getattr(needed, count),
            moment=publish_at,
            scheduled_post_id=scheduled_post_id,
        )
