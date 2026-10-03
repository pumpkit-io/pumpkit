"""DB I/O for the ``purchases`` table.

Pure persistence helpers — no Stripe calls, no business decisions, no commits.
The purchases mediator composes these inside the webhook transaction.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.purchases import Product
from app.db.models import Purchase


async def create_pending_purchase(
    db: AsyncSession,
    *,
    purchase_id: str,
    user_id: str,
    product: Product,
    stripe_checkout_session_id: str,
) -> Purchase:
    purchase = Purchase(
        id=purchase_id,
        user_id=user_id,
        product_id=product.id,
        status="pending",
        stripe_checkout_session_id=stripe_checkout_session_id,
        currency=product.currency,
        amount_subtotal_cents=product.amount_cents,
        refunded_amount_cents=0,
    )
    db.add(purchase)
    await db.flush()
    return purchase


async def _one(db: AsyncSession, query) -> Optional[Purchase]:
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_purchase_by_id(db: AsyncSession, *, purchase_id: str) -> Optional[Purchase]:
    return await _one(db, select(Purchase).where(Purchase.id == purchase_id))


async def get_purchase_by_session_id(db: AsyncSession, *, session_id: str) -> Optional[Purchase]:
    return await _one(db, select(Purchase).where(Purchase.stripe_checkout_session_id == session_id))


async def get_purchase_by_payment_intent_id(
    db: AsyncSession, *, payment_intent_id: str
) -> Optional[Purchase]:
    return await _one(
        db, select(Purchase).where(Purchase.stripe_payment_intent_id == payment_intent_id)
    )


async def get_purchase_by_charge_id(db: AsyncSession, *, charge_id: str) -> Optional[Purchase]:
    return await _one(db, select(Purchase).where(Purchase.stripe_charge_id == charge_id))


async def mark_purchase_paid(
    db: AsyncSession,
    purchase: Purchase,
    *,
    payment_intent_id: Optional[str],
    charge_id: Optional[str],
    amount_subtotal_cents: int,
    amount_tax_cents: Optional[int],
    amount_total_cents: Optional[int],
) -> None:
    purchase.status = "paid"
    purchase.stripe_payment_intent_id = payment_intent_id
    purchase.stripe_charge_id = charge_id
    purchase.amount_subtotal_cents = amount_subtotal_cents
    purchase.amount_tax_cents = amount_tax_cents
    purchase.amount_total_cents = amount_total_cents
    await db.flush()


async def mark_purchase_refunded(
    db: AsyncSession,
    purchase: Purchase,
    *,
    refunded_amount_cents: int,
    is_full: bool,
    charge_id: Optional[str],
) -> None:
    purchase.refunded_amount_cents = refunded_amount_cents
    purchase.status = "refunded" if is_full else "partially_refunded"
    # Backfill the charge id if it was not resolved at checkout time.
    if charge_id is not None and purchase.stripe_charge_id is None:
        purchase.stripe_charge_id = charge_id
    await db.flush()


async def mark_purchase_disputed(
    db: AsyncSession, purchase: Purchase, *, charge_id: Optional[str]
) -> None:
    purchase.status = "disputed"
    if charge_id is not None and purchase.stripe_charge_id is None:
        purchase.stripe_charge_id = charge_id
    await db.flush()


async def mark_purchase_dispute_reinstated(db: AsyncSession, purchase: Purchase) -> None:
    purchase.status = "partially_refunded" if purchase.refunded_amount_cents > 0 else "paid"
    await db.flush()


async def mark_purchase_failed(db: AsyncSession, purchase: Purchase) -> None:
    purchase.status = "failed"
    await db.flush()


async def list_purchases_for_user(db: AsyncSession, *, user_id: str) -> list[Purchase]:
    result = await db.execute(
        select(Purchase)
        .where(Purchase.user_id == user_id)
        .order_by(Purchase.created_at.desc(), Purchase.id.desc())
    )
    return list(result.scalars().all())
