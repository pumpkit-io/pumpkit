# backend/app/api/services/stripe_events.py
"""Per-event idempotency for Stripe webhook handlers.

``try_record_event`` returns ``True`` the first time an ``event_id`` is
seen, ``False`` afterwards. Webhook handlers must short-circuit on
``False`` to avoid double-applying side effects.
"""

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
    """Insert a row keyed by ``event_id``. Returns True on first insert.

    Performs an existence check first to keep the happy path cheap, then
    falls back to an ``IntegrityError``-catching savepoint to handle the
    rare race in which two concurrent webhook handlers both pass the
    existence check and then race on the insert.
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
