from typing import Optional

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
from app.db.models import User
from app.schemas.billing import (
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

    Concurrent first calls for one User create one customer: the User's row is
    locked before the ID is read, so a second request waits and then sees the
    first one's customer. The creation also carries an idempotency key per
    User, so a second call that still reaches the provider (say the commit
    failed after the customer was created, or SQLite, which has no row locks)
    gets the same customer back, for as long as Stripe keeps the key (24
    hours). The lock is
    held across the provider call and released by the early commit, or by the
    end of the request's transaction when the customer already exists.
    """
    await users_service.lock_user(db, user)
    if user.stripe_customer_id:
        return user.stripe_customer_id

    customer_id = await gateway.create_customer(
        email=user.email,
        name=user.display_name,
        user_id=user.id,
        idempotency_key=f"pumpkit-user-{user.id}-customer",
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
    at most one Trial. An abandoned Checkout leaves no Subscription row, so it
    doesn't use up the Trial.

    Subscription rows are written by the `customer.subscription.created`
    webhook, which lands after the Checkout completes. `create_checkout_session`
    keeps a User from completing several Trial Checkouts; see its docstring for
    the window that remains.
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

    Only the User's newest Checkout can be completed: the User's still-open
    Checkouts are expired before the new one is created. Without that, a User
    with no Subscription row could open several Checkouts, each with the
    Trial, and complete them one after another before the first
    `customer.subscription.created` webhook lands. The User's row stays locked
    from the eligibility check to the new Checkout, so concurrent checkouts
    for one User run one at a time (the lock is held across the provider
    calls and released when the request's transaction ends).

    Remaining window: a Checkout completed before this one started is no
    longer open, so nothing expires it, and until its webhook writes the
    Subscription row the User still looks eligible. A Checkout started in
    that window (usually seconds) gets a second Trial.
    """
    plan_key = checkout_request.plan_key
    if plan_key not in settings.BILLING_PLAN_KEYS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown Plan.")

    plan = next((p for p in await gateway.list_plans([plan_key]) if p.key == plan_key), None)
    if plan is None:
        raise BillingProviderError(f"Configured Plan {plan_key} has no active recurring price")

    customer_id = await _ensure_stripe_customer(db, gateway, user)
    # Take the User's lock again: creating the customer committed and released it.
    await users_service.lock_user(db, user)
    trial_period_days = await _trial_period_days_for(db, user)
    await gateway.expire_open_checkouts(customer_id=customer_id)
    session = await gateway.create_subscription_checkout(
        customer_id=customer_id,
        price_id=plan.price_id,
        quantity=1,  # A Subscription is always for one seat; the client never chooses.
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
    Verify the webhook through the gateway, deduplicate by event ID, and sync
    the customer it nudges about (ADR 0004).

    The `stripe_events` insert and the sync share ONE transaction, committed at
    the end. Handlers must not commit. If anything raises, including the
    gateway during the sync, the whole event rolls back (the dedup row too)
    and the response is an error (502 for the gateway, else 500), so Stripe
    retries it.
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
        await _dispatch_event(db, gateway, event)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


def _is_nudge(event: WebhookEvent) -> bool:
    """Whether the event says a customer's Subscriptions may have changed."""
    return event.type.startswith("customer.subscription.") or (
        event.type == "checkout.session.completed"
    )


async def _dispatch_event(db: AsyncSession, gateway: BillingGateway, event: WebhookEvent) -> None:
    """Act on a verified, first-seen Stripe event. Must not commit."""
    if not _is_nudge(event):
        logger.info("Unhandled Stripe webhook event type: %s (event_id=%s)", event.type, event.id)
        return
    if event.customer_id is None:
        logger.error("Stripe %s event names no customer (event_id=%s)", event.type, event.id)
        return
    await _sync_customer(db, gateway, customer_id=event.customer_id, event_id=event.id)


async def _sync_customer(
    db: AsyncSession, gateway: BillingGateway, *, customer_id: str, event_id: str
) -> None:
    """
    Sync the customer's Subscriptions from Stripe. The User's row stays locked
    across the Stripe call, so webhooks for one customer run one after another
    and none can write an older state last.
    """
    user = await users_service.get_user_by_stripe_customer_id(db, customer_id)
    if user is None:
        logger.error(
            "Stripe webhook for unknown customer (event_id=%s, customer_id=%s)",
            event_id,
            customer_id,
        )
        return
    await users_service.lock_user(db, user)
    await subscriptions_service.sync_customer(db, gateway, user_id=user.id, customer_id=customer_id)
