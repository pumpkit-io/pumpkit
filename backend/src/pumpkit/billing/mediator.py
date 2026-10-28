from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.auth.service.users as users_service
from pumpkit.auth.models import User
from pumpkit.billing import service
from pumpkit.billing.gateway import (
    BillingGateway,
    BillingProviderError,
    WebhookEvent,
    WebhookSignatureError,
)
from pumpkit.billing.schemas import (
    BillingMeResponse,
    BillingPortalResponse,
    BillingSubscriptionResponse,
    CheckoutRequest,
    CheckoutResponse,
    PlanResponse,
    PlansListResponse,
)
from pumpkit.billing.terms import TERMS_VERSION
from pumpkit.core.config import BILLING_PAGE, settings
from pumpkit.core.errors import BadRequestError, ConflictError, RefusedError
from pumpkit.core.logging import logger
from pumpkit.core.schemas import LinkToolResponse


async def get_billing_me(db: AsyncSession, user: User) -> BillingMeResponse:
    """
    What the User holds and may do, from Pumpkit's copy only: never a call to
    the billing provider, so it reflects the last sync (ADR 0004).
    """
    subscription = await service.get_user_subscription(db, user_id=user.id)
    offer = await service.get_subscription_offer(db, user_id=user.id)
    return BillingMeResponse(
        subscription=(
            None
            if subscription is None
            else BillingSubscriptionResponse(
                status=subscription.status,
                plan_key=subscription.plan_key,
                current_period_end=subscription.current_period_end,
                cancel_at_period_end=subscription.cancel_at_period_end,
            )
        ),
        subscribed=service.is_subscribed(subscription),
        may_subscribe=offer.may_subscribe,
        trial_days=offer.trial_days,
    )


def subscription_link() -> LinkToolResponse:
    """Where the User subscribes or manages their Subscription, unless the Instance sells no Plans."""
    if not service.sells_plans():
        return LinkToolResponse(
            message="This Instance sells no Plans: you can use all of Pumpkit without a "
            "Subscription.",
            url=None,
        )
    url = settings.billing_page_url()
    return LinkToolResponse(
        message=f"Subscribe or manage your Subscription on the Settings page: {url}", url=url
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
        ],
        terms_version=TERMS_VERSION if service.requires_terms_acceptance() else None,
    )


async def _ensure_stripe_customer(db: AsyncSession, gateway: BillingGateway, user: User) -> str:
    """
    Return the User's Stripe customer ID, creating the customer the first time; commits then.

    The User's row is locked across the provider call, so concurrent first calls create one
    customer. A per-User idempotency key covers what the lock can't (a failed commit, SQLite
    without row locks) for as long as Stripe keeps the key (24 hours).
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
    # Sanctioned early commit: persist the customer before the next Stripe call can fail.
    await db.commit()
    return customer_id


def _require_terms_acceptance(checkout_request: CheckoutRequest) -> None:
    """Raise unless the request ticks every box for the current Terms version."""
    if not (
        checkout_request.accepted_terms
        and checkout_request.requested_immediate_start
        and checkout_request.approved_specific_clauses
        and checkout_request.terms_version
    ):
        raise RefusedError("Accept the Terms to subscribe.")
    if checkout_request.terms_version != TERMS_VERSION:
        raise ConflictError(
            "The Terms have changed. Please review the current Terms and accept them again."
        )


async def create_checkout_session(
    db: AsyncSession,
    gateway: BillingGateway,
    user: User,
    checkout_request: CheckoutRequest,
) -> CheckoutResponse:
    """
    Create a Stripe Checkout for one unit of a configured Plan, with a Trial if the User is eligible.

    Where the Instance has Terms (ADR 0011), a missing acceptance is a 422 and a Terms version
    other than the current one a 409; an unknown Plan key is a 400; all before any Stripe call.
    Otherwise the User's acceptance of the Terms, if any, is recorded and committed first, so
    it stands whatever Stripe does next (ADR 0010). A Plan Stripe can't resolve, or any
    gateway failure, is a 502. A User has at most one Running Subscription, so one who holds
    it gets a 409. The sync from Stripe runs first (ADR 0004), so a Subscription no webhook has
    reported still blocks the Checkout and uses up the Trial. Otherwise `incomplete`
    Subscriptions are cancelled and open Checkouts expired, so only the newest attempt can
    start a Subscription. The User's row stays locked from the sync to the new Checkout, so
    concurrent Checkouts for one User run one at a time.
    """
    terms_apply = service.requires_terms_acceptance()
    if terms_apply:
        _require_terms_acceptance(checkout_request)
    plan_key = checkout_request.plan_key
    if plan_key not in settings.BILLING_PLAN_KEYS:
        raise BadRequestError("Unknown Plan.")

    if terms_apply:
        await service.record_terms_acceptance(
            db,
            user_id=user.id,
            terms_version=TERMS_VERSION,
            accepted_terms=True,
            requested_immediate_start=True,
            approved_specific_clauses=True,
        )
        # Sanctioned early commit: the acceptance is evidence and must outlive a failed Stripe call.
        await db.commit()

    plan = next((p for p in await gateway.list_plans([plan_key]) if p.key == plan_key), None)
    if plan is None:
        raise BillingProviderError(f"Configured Plan {plan_key} has no active recurring price")

    customer_id = await _ensure_stripe_customer(db, gateway, user)
    # Take the User's lock again: creating the customer committed and released it.
    await users_service.lock_user(db, user)
    await service.sync_customer(db, gateway, user_id=user.id, customer_id=customer_id)
    offer = await service.get_subscription_offer(db, user_id=user.id)
    if not offer.may_subscribe:
        # Commit before raising, or the 409 rolls back the sync of what Stripe just said.
        await db.commit()
        raise ConflictError(
            "You already have a Subscription. Manage it in the billing portal.",
            fix_page=BILLING_PAGE,
        )
    for incomplete in await service.list_incomplete_subscriptions(db, user_id=user.id):
        await gateway.cancel_subscription(subscription_id=incomplete.stripe_subscription_id)
    await gateway.expire_open_checkouts(customer_id=customer_id)
    session = await gateway.create_subscription_checkout(
        customer_id=customer_id,
        price_id=plan.price_id,
        quantity=1,  # A Subscription is always for one seat; the client never chooses.
        user_id=user.id,
        trial_period_days=offer.trial_days,
    )
    await db.commit()
    return CheckoutResponse(url=session.url, session_id=session.id)


async def create_billing_portal_session(
    db: AsyncSession,
    gateway: BillingGateway,
    user: User,
) -> BillingPortalResponse:
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
    Verify the webhook, deduplicate by event ID, and sync the customer it nudges about (ADR 0004).

    The `stripe_events` insert and the sync share one transaction, committed here; handlers
    must not commit. Anything that raises rolls the whole event back, dedup row included, and
    the error response (502 for the gateway, else 500) makes Stripe retry.
    """
    if not signature:
        raise BadRequestError("Missing Stripe signature header.")

    try:
        event = gateway.verify_webhook(payload=payload, signature=signature)
    except WebhookSignatureError:
        logger.warning("Rejected a Stripe webhook that failed verification", exc_info=True)
        raise BadRequestError("Invalid signature.")

    try:
        is_new = await service.try_record_event(db, event_id=event.id, event_type=event.type)
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
    await service.sync_customer(db, gateway, user_id=user.id, customer_id=customer_id)
