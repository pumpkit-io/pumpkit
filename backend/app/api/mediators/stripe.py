from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.stripe_events as stripe_events_service
import app.api.services.subscriptions as subscriptions_service
import app.api.services.users as users_service
from app.core.billing_gateway import (
    BillingGateway,
    BillingProviderError,
    WebhookEvent,
    WebhookSignatureError,
)
from app.core.config import settings
from app.core.logger import logger
from app.db.models import SubscriptionStatus, User
from app.schemas.stripe import (
    BillingPortalResponse,
    CheckoutRequest,
    CheckoutResponse,
    PlanResponse,
    PlansListResponse,
    SubscriptionMeResponse,
)


async def get_subscription_me(db: AsyncSession, user: User) -> SubscriptionMeResponse:
    """
    Return the authenticated user's latest subscription view.
    """
    subscription = await subscriptions_service.get_latest_subscription_for_user(
        db=db, user_id=user.id
    )

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
        is_active=subscriptions_service.is_subscription_active(subscription),
    )


async def list_plans(gateway: BillingGateway) -> PlansListResponse:
    """
    Return the configured Plans, in settings order, with their current prices.
    A configured Plan the provider can't resolve is left out and logged, so one
    misconfigured key doesn't hide the others.
    """
    keys = settings.BILLING_PLAN_KEYS
    resolved = {plan.key: plan for plan in await gateway.list_plans(keys)}
    for key in keys:
        if key not in resolved:
            logger.error("Configured Plan %s has no active recurring price in Stripe", key)
    return PlansListResponse(
        data=[
            PlanResponse(
                key=plan.key,
                product_name=plan.product_name,
                amount=plan.amount,
                currency=plan.currency,
                interval=plan.interval,
                interval_count=plan.interval_count,
            )
            for key in keys
            if (plan := resolved.get(key))
        ]
    )


async def _ensure_stripe_customer(db: AsyncSession, gateway: BillingGateway, user: User) -> str:
    """
    Return the User's Stripe customer ID, creating the customer through the
    gateway the first time. Commits when it creates one.
    """
    if user.stripe_customer_id:
        return user.stripe_customer_id

    customer_id = await gateway.create_customer(
        email=user.email, name=user.display_name, user_id=user.id
    )
    await users_service.set_stripe_customer_id(db, user, customer_id)
    # Sanctioned early commit: persist the new Stripe customer before the next
    # Stripe call, so a failure there can't lose it and a retry never creates a
    # duplicate customer.
    await db.commit()
    return customer_id


async def _trial_period_days_for(db: AsyncSession, user: User) -> Optional[int]:
    """
    The Trial a Checkout for this User should start with: the configured length
    for a User who has never had a Subscription, otherwise none. Each User gets
    at most one Trial.

    Subscription rows are written by the `customer.subscription.created`
    webhook, so a second Checkout started before that webhook lands still
    sees the User as eligible.
    """
    days = settings.BILLING_TRIAL_PERIOD_DAYS
    if days == 0:  # Trials are off; Stripe rejects a zero-day Trial.
        return None
    if await subscriptions_service.has_had_subscription(db, user_id=user.id):
        return None
    return days


async def create_checkout_session(
    db: AsyncSession,
    gateway: BillingGateway,
    user: User,
    checkout_request: CheckoutRequest,
) -> CheckoutResponse:
    """
    Create a Stripe Checkout for one unit of a configured Plan, with a Trial
    if the User is eligible. An unknown Plan key is the client's fault (400)
    and reaches no Stripe call; a configured Plan Stripe can't resolve is a
    provider failure (502).
    """
    plan_key = checkout_request.plan_key
    if plan_key not in settings.BILLING_PLAN_KEYS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown Plan.")

    plan = next((p for p in await gateway.list_plans([plan_key]) if p.key == plan_key), None)
    if plan is None:
        raise BillingProviderError(f"Configured Plan {plan_key} has no active recurring price")

    trial_period_days = await _trial_period_days_for(db, user)
    customer_id = await _ensure_stripe_customer(db, gateway, user)
    session = await gateway.create_subscription_checkout(
        customer_id=customer_id,
        price_id=plan.price_id,
        user_id=user.id,
        trial_period_days=trial_period_days,
    )
    return CheckoutResponse(url=session.url, session_id=session.id)


async def create_billing_portal_session(
    db: AsyncSession,
    gateway: BillingGateway,
    user: User,
) -> BillingPortalResponse:
    """
    Create a Stripe billing portal session to let the user manage their subscriptions.
    """
    customer_id = await _ensure_stripe_customer(db, gateway, user)
    url = await gateway.create_portal_url(customer_id=customer_id)
    return BillingPortalResponse(url=url)


async def handle_webhook(
    db: AsyncSession,
    gateway: BillingGateway,
    payload: bytes,
    signature: Optional[str],
) -> None:
    """
    Verify the webhook through the gateway, deduplicate by event id, and dispatch.

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
        event = gateway.verify_webhook(payload=payload, signature=signature)
    except WebhookSignatureError:
        logger.warning("Rejected a Stripe webhook that failed verification", exc_info=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature.")

    try:
        is_new = await stripe_events_service.try_record_event(
            db, event_id=event.id, event_type=event.type
        )
        if not is_new:
            logger.info("Ignoring replayed Stripe event %s (%s)", event.id, event.type)
            await db.rollback()
            return
        await _dispatch_event(db, event)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def _dispatch_event(db: AsyncSession, event: WebhookEvent) -> None:
    """Route a verified, first-seen Stripe event to its handler. Must not commit."""
    match event.type:
        case (
            "customer.subscription.created"
            | "customer.subscription.updated"
            | "customer.subscription.deleted"
        ):
            await _handle_subscription_event(
                db=db, subscription=event.data_object, event_id=event.id
            )
        case "checkout.session.completed":
            # The subsequent customer.subscription.created event writes the row.
            # Log for observability.
            logger.info(
                "Stripe checkout.session.completed (session_id=%s, client_reference_id=%s)",
                event.data_object.get("id"),
                event.data_object.get("client_reference_id"),
            )
        case _:
            logger.info(
                "Unhandled Stripe webhook event type: %s (event_id=%s)", event.type, event.id
            )


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

    user = await subscriptions_service.get_user_by_stripe_customer_id(
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

    await subscriptions_service.upsert_subscription(
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
