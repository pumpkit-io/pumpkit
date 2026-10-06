"""Per-event idempotency: Stripe webhook handlers short-circuit when `try_record_event` is False."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import StripeEvent


async def try_record_event(
    db: AsyncSession,
    *,
    event_id: str,
    event_type: str,
) -> bool:
    """
    Record `event_id`, returning True only the first time it is seen.

    The existence check keeps the common path cheap; the savepoint catches two
    concurrent handlers that both pass it and race on the insert.
    """
    existing = await db.execute(select(StripeEvent.id).where(StripeEvent.id == event_id))
    if existing.scalar_one_or_none() is not None:
        return False

    try:
        async with db.begin_nested():
            db.add(StripeEvent(id=event_id, type=event_type))
            await db.flush()
    except IntegrityError:
        return False
    return True
