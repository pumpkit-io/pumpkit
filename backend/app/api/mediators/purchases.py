"""One-time purchase checkout and Stripe webhook handlers.

Webhook handlers run inside the dispatcher's transaction (see
mediators/stripe.handle_webhook): they flush via services and call hooks, but
never commit.
"""

import asyncio
from typing import Any, Optional

import stripe
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.hooks.purchases as purchase_hooks
import app.api.services.purchases as purchases_service
import app.api.services.stripe_customers as stripe_customers_service
from app.core.config import settings
from app.core.ids import ulid_with_prefix
from app.core.logger import logger
from app.core.purchases import get_product
from app.db.models import Purchase, User
from app.schemas.billing import PurchaseCheckoutResponse

PURCHASE_METADATA_KIND = "purchase"


async def create_checkout_session(
    db: AsyncSession,
    *,
    user: User,
    product_id: str,
) -> PurchaseCheckoutResponse:
    """Validate the product, create a Stripe Checkout Session, persist a pending row."""
    try:
        product = get_product(product_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    customer_id = await stripe_customers_service.ensure_stripe_customer(db=db, user=user)

    # Pre-generate the purchase id so it can travel in Stripe metadata: it lets
    # payment_intent.payment_failed find the pending row before the session completes.
    purchase_id = ulid_with_prefix("purchase")
    metadata = {
        "kind": PURCHASE_METADATA_KIND,
        "purchase_id": purchase_id,
        "product_id": product.id,
        "user_id": user.id,
    }

    session_params: dict[str, Any] = {
        "mode": "payment",
        "customer": customer_id,
        "client_reference_id": user.id,
        "line_items": [
            {
                "price_data": {
                    "currency": product.currency,
                    "unit_amount": product.amount_cents,
                    "product_data": {"name": product.name, "description": product.description},
                },
                "quantity": 1,
            }
        ],
        "metadata": metadata,
        "payment_intent_data": {"metadata": metadata},
        "success_url": (
            f"{settings.STRIPE_CHECKOUT_SUCCESS_URL}"
            f"?kind={PURCHASE_METADATA_KIND}&session_id={{CHECKOUT_SESSION_ID}}"
        ),
        "cancel_url": f"{settings.STRIPE_CHECKOUT_CANCEL_URL}?kind={PURCHASE_METADATA_KIND}",
    }

    try:
        session = await asyncio.to_thread(stripe.checkout.Session.create, **session_params)
    except stripe.StripeError as exc:
        logger.exception("Failed to create purchase checkout session for user_id=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=getattr(exc, "user_message", None)
            or "Could not start checkout. Please try again.",
        )

    if not session.url:
        logger.error("Stripe returned a checkout session without a URL (session_id=%s)", session.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start checkout. Please try again later.",
        )

    await purchases_service.create_pending_purchase(
        db,
        purchase_id=purchase_id,
        user_id=user.id,
        product=product,
        stripe_checkout_session_id=session.id,
    )
    await db.commit()
    return PurchaseCheckoutResponse(url=session.url, session_id=session.id)


async def handle_checkout_completed(db: AsyncSession, *, session: dict[str, Any]) -> None:
    await _settle_checkout_session(db, session)


async def handle_checkout_async_payment_succeeded(
    db: AsyncSession, *, session: dict[str, Any]
) -> None:
    """Delayed payment methods: funds arrived after the session already completed."""
    await _settle_checkout_session(db, session)


async def handle_checkout_session_expired(db: AsyncSession, *, session: dict[str, Any]) -> None:
    await _fail_pending_for_session(db, session)


async def handle_checkout_async_payment_failed(
    db: AsyncSession, *, session: dict[str, Any]
) -> None:
    await _fail_pending_for_session(db, session)


async def _fail_pending_for_session(db: AsyncSession, session: dict[str, Any]) -> None:
    purchase = await _find_purchase_for_session(db, session)
    if purchase is None or purchase.status != "pending":
        return
    await purchases_service.mark_purchase_failed(db, purchase)


async def _settle_checkout_session(db: AsyncSession, session: dict[str, Any]) -> None:
    purchase = await _find_purchase_for_session(db, session)
    if purchase is None:
        purchase = await _create_purchase_from_metadata(db, session)
        if purchase is None:
            return
    if purchase.status != "pending":
        logger.info("Purchase %s already %s; ignoring settlement", purchase.id, purchase.status)
        return
    if session.get("payment_status") != "paid":
        # Delayed payment methods complete the session before funds arrive.
        logger.info("Purchase %s session not paid yet", purchase.id)
        return

    try:
        product = get_product(purchase.product_id)
    except ValueError:
        logger.error("Purchase %s references unknown product %s", purchase.id, purchase.product_id)
        await purchases_service.mark_purchase_failed(db, purchase)
        return

    # Validates the subtotal only: promotion codes and automatic tax are not
    # enabled for one-time checkouts, so subtotal must equal the catalog price.
    amount_subtotal = session.get("amount_subtotal")
    currency = (session.get("currency") or "").lower()
    if amount_subtotal != product.amount_cents or currency != product.currency:
        logger.error(
            "Purchase %s amount mismatch (got %s %s, expected %s %s)",
            purchase.id,
            amount_subtotal,
            currency,
            product.amount_cents,
            product.currency,
        )
        await purchases_service.mark_purchase_failed(db, purchase)
        return

    payment_intent_id = session.get("payment_intent")
    charge_id = await _resolve_charge_id(payment_intent_id) if payment_intent_id else None
    total_details = session.get("total_details") or {}
    amount_tax = total_details.get("amount_tax")

    await purchases_service.mark_purchase_paid(
        db,
        purchase,
        payment_intent_id=payment_intent_id,
        charge_id=charge_id,
        amount_subtotal_cents=amount_subtotal,
        amount_tax_cents=amount_tax if isinstance(amount_tax, int) else None,
        amount_total_cents=session.get("amount_total"),
    )
    await purchase_hooks.on_purchase_paid(db, purchase)


async def _create_purchase_from_metadata(
    db: AsyncSession, session: dict[str, Any]
) -> Optional[Purchase]:
    """Recover a purchase whose pending row was never persisted (checkout crash)."""
    metadata = session.get("metadata") or {}
    user_id = metadata.get("user_id")
    session_id = session.get("id")
    if metadata.get("kind") != PURCHASE_METADATA_KIND or not user_id or not session_id:
        logger.error("checkout completed for unknown purchase (session_id=%s)", session_id)
        return None
    try:
        product = get_product(metadata.get("product_id") or "")
    except ValueError:
        logger.error("checkout completed with invalid product metadata (session_id=%s)", session_id)
        return None
    purchase_id = metadata.get("purchase_id") or ulid_with_prefix("purchase")
    if await purchases_service.get_purchase_by_id(db, purchase_id=purchase_id) is not None:
        logger.error("Purchase %s belongs to a different session (got %s)", purchase_id, session_id)
        return None
    return await purchases_service.create_pending_purchase(
        db,
        purchase_id=purchase_id,
        user_id=user_id,
        product=product,
        stripe_checkout_session_id=session_id,
    )


async def handle_charge_refunded(db: AsyncSession, *, charge: dict[str, Any]) -> None:
    purchase = await _find_purchase_for_charge(
        db, charge_id=charge.get("id"), payment_intent_id=charge.get("payment_intent")
    )
    if purchase is None:
        logger.info("charge.refunded for a non-purchase charge (charge_id=%s)", charge.get("id"))
        return

    amount = charge.get("amount") or 0
    amount_refunded = charge.get("amount_refunded") or 0
    if amount <= 0 or amount_refunded <= purchase.refunded_amount_cents:
        return  # nothing new to apply

    is_full = amount_refunded >= amount
    await purchases_service.mark_purchase_refunded(
        db,
        purchase,
        refunded_amount_cents=amount_refunded,
        is_full=is_full,
        charge_id=charge.get("id"),
    )
    await purchase_hooks.on_purchase_reversed(
        db, purchase, "refunded" if is_full else "partially_refunded"
    )


async def handle_charge_dispute_funds_withdrawn(
    db: AsyncSession, *, dispute: dict[str, Any]
) -> None:
    purchase = await _find_purchase_for_charge(
        db, charge_id=dispute.get("charge"), payment_intent_id=dispute.get("payment_intent")
    )
    if purchase is None or purchase.status not in ("paid", "partially_refunded"):
        return
    await purchases_service.mark_purchase_disputed(db, purchase, charge_id=dispute.get("charge"))
    await purchase_hooks.on_purchase_reversed(db, purchase, "disputed")


async def handle_charge_dispute_funds_reinstated(
    db: AsyncSession, *, dispute: dict[str, Any]
) -> None:
    purchase = await _find_purchase_for_charge(
        db, charge_id=dispute.get("charge"), payment_intent_id=dispute.get("payment_intent")
    )
    if purchase is None or purchase.status != "disputed":
        return
    await purchases_service.mark_purchase_dispute_reinstated(db, purchase)
    await purchase_hooks.on_purchase_reinstated(db, purchase)


async def handle_payment_intent_failed(db: AsyncSession, *, payment_intent: dict[str, Any]) -> None:
    """Log only: Checkout reuses the PaymentIntent, so a decline is not final.

    Terminal failure is signalled by checkout.session.expired / async_payment_failed.
    """
    metadata = payment_intent.get("metadata") or {}
    purchase_id = metadata.get("purchase_id")
    purchase = None
    if purchase_id:
        purchase = await purchases_service.get_purchase_by_id(db, purchase_id=purchase_id)
    logger.info(
        "Payment attempt failed (payment_intent_id=%s, purchase_id=%s)",
        payment_intent.get("id"),
        purchase.id if purchase else None,
    )


def is_purchase_event(data_object: dict[str, Any]) -> bool:
    return (data_object.get("metadata") or {}).get("kind") == PURCHASE_METADATA_KIND


async def _find_purchase_for_session(
    db: AsyncSession, session: dict[str, Any]
) -> Optional[Purchase]:
    session_id = session.get("id", "")
    purchase = await purchases_service.get_purchase_by_session_id(db, session_id=session_id)
    if purchase is None:
        purchase_id = (session.get("metadata") or {}).get("purchase_id")
        if purchase_id:
            candidate = await purchases_service.get_purchase_by_id(db, purchase_id=purchase_id)
            if candidate is not None and candidate.stripe_checkout_session_id == session_id:
                purchase = candidate
    return purchase


async def _find_purchase_for_charge(
    db: AsyncSession, *, charge_id: Optional[str], payment_intent_id: Optional[str]
) -> Optional[Purchase]:
    if charge_id:
        purchase = await purchases_service.get_purchase_by_charge_id(db, charge_id=charge_id)
        if purchase is not None:
            return purchase
    if payment_intent_id:
        return await purchases_service.get_purchase_by_payment_intent_id(
            db, payment_intent_id=payment_intent_id
        )
    return None


async def _resolve_charge_id(payment_intent_id: str) -> Optional[str]:
    """Return the latest charge id for a PaymentIntent, or None on failure."""
    try:
        pi = await asyncio.to_thread(
            stripe.PaymentIntent.retrieve, payment_intent_id, expand=["latest_charge"]
        )
    except stripe.StripeError:
        logger.exception("Failed to retrieve PaymentIntent %s", payment_intent_id)
        return None
    latest = pi.get("latest_charge") if isinstance(pi, dict) else getattr(pi, "latest_charge", None)
    if isinstance(latest, str):
        return latest
    if isinstance(latest, dict):
        return latest.get("id")
    return getattr(latest, "id", None)
