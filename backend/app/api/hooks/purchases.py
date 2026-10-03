"""Extension points for one-time purchases.

This is where your app grants or revokes whatever a product unlocks. Each hook
runs inside the Stripe webhook transaction: write with the given `db` session,
never commit, and raise to abort (Stripe will retry the event).

Hooks are idempotent by construction: the dispatcher deduplicates Stripe events
and each purchase status transition fires its hook at most once.
"""

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import logger
from app.db.models import Purchase

ReversalReason = Literal["refunded", "partially_refunded", "disputed"]


async def on_purchase_paid(db: AsyncSession, purchase: Purchase) -> None:
    """Called once when a purchase is confirmed paid. Grant the product here."""
    logger.info(
        "Purchase paid (purchase_id=%s, user_id=%s, product_id=%s)",
        purchase.id,
        purchase.user_id,
        purchase.product_id,
    )


async def on_purchase_reversed(
    db: AsyncSession, purchase: Purchase, reason: ReversalReason
) -> None:
    """Called when money is taken back (refund or dispute). Revoke access here."""
    logger.info(
        "Purchase reversed (purchase_id=%s, reason=%s, refunded_amount_cents=%s)",
        purchase.id,
        reason,
        purchase.refunded_amount_cents,
    )


async def on_purchase_reinstated(db: AsyncSession, purchase: Purchase) -> None:
    """Called when a dispute is won and the funds return. Re-grant here."""
    logger.info("Purchase reinstated after dispute (purchase_id=%s)", purchase.id)
