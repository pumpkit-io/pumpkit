import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional

import stripe
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.purchases as purchases_mediator
import app.api.services.stripe as stripe_service
import app.api.services.stripe_customers as stripe_customers_service
import app.api.services.stripe_events as stripe_events_service
from app.core.config import settings
from app.core.logger import logger
from app.db.models import SubscriptionStatus, User
from app.schemas.stripe import (
    BillingPortalResponse,
    CheckoutRequest,
    CheckoutResponse,
    PriceProduct,
    PriceRecurring,
    PriceResponse,
    PricesListResponse,
    SubscriptionMeResponse,
    TrialRequest,
    TrialResponse,
)

# Setup the Stripe API key at the module level
stripe.api_key = settings.STRIPE_SECRET_KEY


async def get_subscription_me(db: AsyncSession, user: User) -> SubscriptionMeResponse:
    """
    Return the authenticated user's latest subscription view.
    """
    subscription = await stripe_service.get_latest_subscription_for_user(db=db, user_id=user.id)

    if subscription is None:
        # No subscription found - return the default status indicating no active subscription
        return SubscriptionMeResponse(
            status=None,
            stripe_price_id=None,
            current_period_end=None,
            cancel_at_period_end=False,
            is_active=False,
        )

    return SubscriptionMeResponse(
        status=subscription.status,
        stripe_price_id=subscription.stripe_price_id,
        current_period_end=subscription.current_period_end,
        cancel_at_period_end=subscription.cancel_at_period_end,
        is_active=stripe_service.is_subscription_active(subscription),
    )


async def list_prices() -> PricesListResponse:
    """
    Return all active Stripe prices with their parent products expanded.
    """
    # Fetch the prices
    try:
        prices = await asyncio.to_thread(
            stripe.Price.list,
            active=True,
            expand=["data.product"],
            limit=100,
        )
    except stripe.StripeError:
        logger.exception("Failed to list Stripe prices")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not load pricing information. Please try again later.",
        )

    # Parse the relevant fields of each product and price
    data: list[PriceResponse] = []
    for stripe_price in prices.data:
        # stripe>=15 resources are not dicts; convert (recursively) so .get() works.
        price = stripe_price.to_dict()
        product_payload: Optional[PriceProduct] = None
        product = price.get("product")
        if isinstance(product, dict) and not product.get("deleted"):
            product_payload = PriceProduct(
                id=product["id"],
                name=product.get("name"),
                description=product.get("description"),
            )

        recurring_payload: Optional[PriceRecurring] = None
        recurring = price.get("recurring")
        if recurring:
            recurring_payload = PriceRecurring(
                interval=recurring["interval"],
                interval_count=recurring.get("interval_count", 1),
            )

        data.append(
            PriceResponse(
                id=price["id"],
                currency=price["currency"],
                unit_amount=price.get("unit_amount"),
                recurring=recurring_payload,
                product=product_payload,
            )
        )

    return PricesListResponse(data=data)


async def create_checkout_session(
    db: AsyncSession,
    user: User,
    checkout_request: CheckoutRequest,
) -> CheckoutResponse:
    """
    Create a Stripe checkout session for a subscription purchase.
    """
    customer_id = await stripe_customers_service.ensure_stripe_customer(db=db, user=user)

    # Setup the checkout session
    session_params: dict[str, Any] = {
        "mode": "subscription",
        "customer": customer_id,
        "client_reference_id": user.id,
        "line_items": [{"price": checkout_request.price_id, "quantity": checkout_request.quantity}],
        "success_url": settings.STRIPE_CHECKOUT_SUCCESS_URL,
        "cancel_url": settings.STRIPE_CHECKOUT_CANCEL_URL,
        "allow_promotion_codes": True,
    }
    if checkout_request.trial_period_days is not None:
        session_params["subscription_data"] = {
            "trial_period_days": checkout_request.trial_period_days
        }

    try:
        session = await asyncio.to_thread(stripe.checkout.Session.create, **session_params)
    except stripe.StripeError as exc:
        logger.exception(
            "Failed to create Stripe Checkout Session for user_id=%s price_id=%s",
            user.id,
            checkout_request.price_id,
        )
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

    return CheckoutResponse(url=session.url, session_id=session.id)


async def create_billing_portal_session(
    db: AsyncSession,
    user: User,
) -> BillingPortalResponse:
    """
    Create a Stripe billing portal session to let the user manage their subscriptions.
    """
    customer_id = await stripe_customers_service.ensure_stripe_customer(db=db, user=user)

    try:
        portal = await asyncio.to_thread(
            stripe.billing_portal.Session.create,
            customer=customer_id,
            return_url=settings.STRIPE_BILLING_PORTAL_RETURN_URL,
        )
    except stripe.StripeError:
        logger.exception("Failed to create Stripe billing portal session for user_id=%s", user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not open the billing portal. Please try again later.",
        )

    return BillingPortalResponse(url=portal.url)


async def start_trial(
    db: AsyncSession,
    user: User,
    trial_request: TrialRequest,
) -> TrialResponse:
    """
    Start a cardless trial by creating a Stripe subscription with no payment method attached.
    When the trial ends without a card, Stripe will cancel the subscription automatically.
    """
    customer_id = await stripe_customers_service.ensure_stripe_customer(db=db, user=user)

    try:
        created = await asyncio.to_thread(
            stripe.Subscription.create,
            customer=customer_id,
            items=[{"price": trial_request.price_id}],
            trial_period_days=trial_request.trial_period_days,
            # If the trial ends and there's still no payment method, cancel the subscription.
            trial_settings={"end_behavior": {"missing_payment_method": "cancel"}},
            # Save the default payment method (if provided) on the subscription, so if the user later
            # goes to the billing portal and adds a card, it will be attached to the subscription and the
            # trial can convert to a paid subscription without the user having to re-enter their card details.
            payment_settings={"save_default_payment_method": "on_subscription"},
            metadata={"user_id": user.id},
        )
    except stripe.StripeError as exc:
        logger.exception(
            "Failed to start Stripe trial for user_id=%s price_id=%s",
            user.id,
            trial_request.price_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=getattr(exc, "user_message", None) or "Could not start trial. Please try again.",
        )

    # stripe>=15 objects have no .get(); convert at the boundary.
    subscription: dict[str, Any] = created.to_dict()

    # The customer.subscription.created webhook will upsert the local row.
    # We still write it here so the response is immediately consistent for
    # a frontend that reads /stripe/me right after this call.
    await _upsert_subscription_from_stripe_object(
        db=db,
        user_id=user.id,
        subscription=subscription,
    )
    await db.commit()

    # Parse the trial end timestamp if available for the response payload
    trial_end: Optional[datetime] = None
    trial_end_ts = subscription.get("trial_end")
    if trial_end_ts:
        trial_end = datetime.fromtimestamp(trial_end_ts, tz=timezone.utc)

    return TrialResponse(
        subscription_id=subscription["id"],
        status=subscription["status"],
        trial_end=trial_end,
    )


async def handle_webhook(
    db: AsyncSession,
    payload: bytes,
    signature: Optional[str],
) -> None:
    """
    Verify the Stripe webhook signature, deduplicate by event id, and dispatch.

    The `stripe_events` insert and every handler write share ONE transaction,
    committed at the end. Handlers must not commit. If a handler raises, the
    whole event rolls back (including the dedup row) and the router returns
    500, so Stripe retries it.
    """
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe signature header.",
        )

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=signature,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        logger.exception("Invalid Stripe webhook payload")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload.")
    except stripe.SignatureVerificationError:
        logger.exception("Invalid Stripe webhook signature")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature.")

    event_id: str = event["id"]
    event_type: str = event["type"]
    # construct_event returns a stripe.Event whose nested objects are
    # StripeObject (attribute-style, no .get()). Handlers use plain dict
    # semantics, so re-parse the raw payload — the signature is already
    # verified, so the bytes are trusted.
    data_object: dict[str, Any] = json.loads(payload)["data"]["object"]

    try:
        is_new = await stripe_events_service.try_record_event(
            db, event_id=event_id, event_type=event_type
        )
        if not is_new:
            logger.info("Ignoring replayed Stripe event %s (%s)", event_id, event_type)
            await db.rollback()
            return
        await _dispatch_event(db, event_type=event_type, event_id=event_id, data_object=data_object)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def _dispatch_event(
    db: AsyncSession,
    *,
    event_type: str,
    event_id: str,
    data_object: dict[str, Any],
) -> None:
    """Route a verified, first-seen Stripe event to its handler. Must not commit."""
    if event_type in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ):
        await _handle_subscription_event(db=db, subscription=data_object, event_id=event_id)
    elif event_type == "checkout.session.completed":
        if purchases_mediator.is_purchase_event(data_object):
            await purchases_mediator.handle_checkout_completed(db, session=data_object)
        else:
            # Subscription checkouts: the subsequent customer.subscription.created
            # event writes the row. Log for observability.
            logger.info(
                "Stripe checkout.session.completed (session_id=%s, client_reference_id=%s)",
                data_object.get("id"),
                data_object.get("client_reference_id"),
            )
    elif (
        event_type == "checkout.session.async_payment_succeeded"
        and purchases_mediator.is_purchase_event(data_object)
    ):
        await purchases_mediator.handle_checkout_async_payment_succeeded(db, session=data_object)
    elif (
        event_type == "checkout.session.async_payment_failed"
        and purchases_mediator.is_purchase_event(data_object)
    ):
        await purchases_mediator.handle_checkout_async_payment_failed(db, session=data_object)
    elif event_type == "checkout.session.expired" and purchases_mediator.is_purchase_event(
        data_object
    ):
        await purchases_mediator.handle_checkout_session_expired(db, session=data_object)
    elif event_type == "charge.refunded":
        await purchases_mediator.handle_charge_refunded(db, charge=data_object)
    elif event_type == "charge.dispute.funds_withdrawn":
        await purchases_mediator.handle_charge_dispute_funds_withdrawn(db, dispute=data_object)
    elif event_type == "charge.dispute.funds_reinstated":
        await purchases_mediator.handle_charge_dispute_funds_reinstated(db, dispute=data_object)
    elif event_type == "payment_intent.payment_failed":
        await purchases_mediator.handle_payment_intent_failed(db, payment_intent=data_object)
    else:
        logger.info("Unhandled Stripe webhook event type: %s (event_id=%s)", event_type, event_id)


async def _handle_subscription_event(
    db: AsyncSession,
    subscription: dict[str, Any],
    event_id: str,
) -> None:
    """
    Upsert the local Subscription row from a Stripe subscription event payload.
    """
    customer_id = _extract_customer_id(subscription)
    if not customer_id:
        logger.error(
            "Stripe subscription event missing customer id (event_id=%s, sub_id=%s)",
            event_id,
            subscription.get("id"),
        )
        return

    user = await stripe_service.get_user_by_stripe_customer_id(
        db=db, stripe_customer_id=customer_id
    )
    if user is None:
        logger.error(
            "Stripe subscription event for unknown customer (event_id=%s, customer_id=%s)",
            event_id,
            customer_id,
        )
        return

    await _upsert_subscription_from_stripe_object(
        db=db,
        user_id=user.id,
        subscription=subscription,
    )


async def _upsert_subscription_from_stripe_object(
    db: AsyncSession,
    user_id: str,
    subscription: Any,
) -> None:
    """
    Extract and upsert relevant fields from a Stripe subscription object.
    """
    sub_id: str = subscription["id"]
    customer_id = _extract_customer_id(subscription)
    price_id = _extract_price_id(subscription)
    sub_status: SubscriptionStatus = subscription["status"]

    # Parse the current period end timestamp if available
    current_period_end: Optional[datetime] = None
    # Current Stripe API versions expose the period end on the subscription items.
    cpe_ts = subscription.get("current_period_end")
    if not cpe_ts:
        first_item = ((subscription.get("items") or {}).get("data") or [None])[0] or {}
        cpe_ts = first_item.get("current_period_end")
    if cpe_ts:
        current_period_end = datetime.fromtimestamp(cpe_ts, tz=timezone.utc)

    cancel_at_period_end = bool(subscription.get("cancel_at_period_end", False))

    await stripe_service.upsert_subscription(
        db=db,
        user_id=user_id,
        stripe_subscription_id=sub_id,
        stripe_customer_id=customer_id or "",
        stripe_price_id=price_id,
        status=sub_status,
        current_period_end=current_period_end,
        cancel_at_period_end=cancel_at_period_end,
    )


def _extract_customer_id(subscription: Any) -> Optional[str]:
    """
    Stripe's customer field can be a string ID or an expanded object.
    """
    customer = subscription.get("customer")
    if isinstance(customer, str):
        return customer
    if isinstance(customer, dict):
        return customer.get("id")
    return None


def _extract_price_id(subscription: Any) -> Optional[str]:
    """
    Pull the first line item's price ID from a Stripe subscription object.
    """
    items = subscription.get("items") or {}
    data = items.get("data") or []
    if not data:
        return None
    price = data[0].get("price") or {}
    if isinstance(price, dict):
        return price.get("id")
    if isinstance(price, str):
        return price
    return None
