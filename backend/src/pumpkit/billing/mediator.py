from dataclasses import asdict
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.auth.service.users as users_service
from pumpkit.auth.models import User
from pumpkit.billing import service
from pumpkit.billing.allowance import (
    SETTINGS_PAGE,
    limits,
    may_buy_top_up,
    sells_top_ups,
    top_up_pack,
)
from pumpkit.billing.gateway import (
    BillingGateway,
    BillingProviderError,
    OneOffPrice,
    WebhookEvent,
    WebhookSignatureError,
)
from pumpkit.billing.models import TopUp
from pumpkit.billing.schemas import (
    BillingMeResponse,
    BillingPortalResponse,
    BillingSubscriptionResponse,
    CheckoutRequest,
    CheckoutResponse,
    OfferedAllowanceResponse,
    OfferedTrialResponse,
    PlanResponse,
    PlansListResponse,
    TermsAcceptanceRequest,
    TopUpCheckoutRequest,
    TopUpOfferResponse,
)
from pumpkit.billing.terms import TERMS_VERSION
from pumpkit.core.analytics import posthog_client
from pumpkit.core.config import BILLING_PAGE, settings
from pumpkit.core.errors import BadRequestError, ConflictError, RefusalError, RefusedError
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
            message="This instance sells no plans: you can use all of Pumpkit without a "
            "subscription.",
            url=None,
        )
    url = settings.billing_page_url()
    return LinkToolResponse(
        message=f"Subscribe or manage your subscription on the Settings page: {url}", url=url
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
        allowance=OfferedAllowanceResponse(**asdict(limits(trial=False))),
        trial=_offered_trial(),
        top_up=await _offered_top_up(gateway),
    )


async def _top_up_price(gateway: BillingGateway) -> Optional[OneOffPrice]:
    """The Top-up's price, or None where the Instance sells no Top-ups."""
    key = settings.BILLING_TOP_UP_KEY
    if not key or not sells_top_ups():
        return None
    price = await gateway.get_one_off_price(key)
    if price is None:
        logger.error("Configured Top-up %s has no active one-off price in Stripe", key)
    return price


async def _offered_top_up(gateway: BillingGateway) -> Optional[TopUpOfferResponse]:
    price = await _top_up_price(gateway)
    if price is None:
        return None
    return TopUpOfferResponse(amount=price.amount, currency=price.currency, **asdict(top_up_pack()))


def _offered_trial() -> Optional[OfferedTrialResponse]:
    days = settings.BILLING_TRIAL_PERIOD_DAYS
    if days == 0:
        return None
    return OfferedTrialResponse(days=days, **asdict(limits(trial=True)))


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


def _require_terms_acceptance(
    checkout_request: TermsAcceptanceRequest, refusal: str = "Accept the Terms to subscribe."
) -> None:
    """Raise unless the request ticks every box for the current Terms version."""
    if not (
        checkout_request.accepted_terms
        and checkout_request.requested_immediate_start
        and checkout_request.approved_specific_clauses
        and checkout_request.terms_version
    ):
        raise RefusedError(refusal)
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
        raise BadRequestError("Unknown plan.")

    if terms_apply:
        await _record_terms_acceptance(db, user)

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
            "You already have a subscription. Manage it in the billing portal.",
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


async def _record_terms_acceptance(db: AsyncSession, user: User) -> None:
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


async def _check_may_buy_top_up(db: AsyncSession, user: User) -> None:
    subscription = await service.get_user_subscription(db, user_id=user.id)
    if may_buy_top_up(subscription):
        return
    status = subscription.status if subscription and service.is_subscribed(subscription) else None
    if status == "trialing":
        message = "You can buy a top-up once your trial ends."
    elif status == "past_due":
        message = "Update your payment method to buy a top-up."
    else:
        message = "Top-ups are for paid subscriptions. Subscribe to buy one."
    raise ConflictError(message, fix_page=SETTINGS_PAGE)


async def create_top_up_checkout(
    db: AsyncSession,
    gateway: BillingGateway,
    user: User,
    checkout_request: TopUpCheckoutRequest,
) -> CheckoutResponse:
    """
    Create a Stripe Checkout that takes one payment for a Top-up (ADR 0017). Only a paid-up paid
    Subscription may buy one, read from Pumpkit's copy; a refusal is a 409 and records nothing.
    The Terms are checked and the acceptance committed before any Stripe call, as for a
    Subscription (ADR 0010). The Top-up itself arrives with the webhook's sync, once paid.
    """
    terms_apply = service.requires_terms_acceptance()
    if terms_apply:
        _require_terms_acceptance(checkout_request, "Accept the Terms to buy a top-up.")
    await _check_may_buy_top_up(db, user)
    if terms_apply:
        await _record_terms_acceptance(db, user)

    price = await _top_up_price(gateway)
    if price is None:
        raise BillingProviderError("The configured Top-up has no active one-off price")
    customer_id = await _ensure_stripe_customer(db, gateway, user)
    session = await gateway.create_top_up_checkout(
        customer_id=customer_id, price_id=price.price_id, user_id=user.id
    )
    await db.commit()
    return CheckoutResponse(url=session.url, session_id=session.id)


class FirstChargeFailed(RefusalError):
    """Subscribing now ended the Trial, but the provider couldn't charge the first period."""

    status_code = 402


async def subscribe_now(db: AsyncSession, gateway: BillingGateway, user: User) -> BillingMeResponse:
    """
    End the User's Trial now, so the provider charges the first period and the paid Allowance
    starts at once. The Terms accepted at Checkout already cover it (ADR 0010).

    The sync from Stripe runs first (ADR 0004), so a Trial that already ended there is a 409, as is
    a User with no trialing Subscription. The User's row stays locked across both provider calls.
    A failed charge leaves the Subscription as Stripe reports it (past due keeps access) and is a 402.
    """
    if not user.stripe_customer_id:
        raise _not_trialing()
    customer_id = user.stripe_customer_id
    await users_service.lock_user(db, user)
    await service.sync_customer(db, gateway, user_id=user.id, customer_id=customer_id)
    subscription = await service.get_user_subscription(db, user_id=user.id)
    if subscription is None or subscription.status != "trialing":
        # Commit before raising, or the 409 rolls back the sync of what Stripe just said.
        await db.commit()
        raise _not_trialing()

    await gateway.end_trial(subscription_id=subscription.stripe_subscription_id)
    await service.sync_customer(db, gateway, user_id=user.id, customer_id=customer_id)
    await db.commit()
    if subscription.status != "active":
        raise FirstChargeFailed(
            "Your trial has ended, but the first payment didn't go through. "
            "Update your payment method to keep writing.",
            fix_page=BILLING_PAGE,
        )
    return await get_billing_me(db, user)


def _not_trialing() -> ConflictError:
    return ConflictError("You're not in a trial, so there's no trial to end.")


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
        added = await _dispatch_event(db, gateway, event)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    for top_up in added:
        posthog_client.capture("top_up_added", distinct_id=top_up.user_id)


# The events that say a customer's Top-ups may have changed: one paid, refunded or disputed.
_TOP_UP_NUDGES = {
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
    "charge.refunded",
    "charge.dispute.created",
}


def _is_subscription_nudge(event: WebhookEvent) -> bool:
    """Whether the event says a customer's Subscriptions may have changed."""
    return event.type.startswith("customer.subscription.") or (
        event.type == "checkout.session.completed"
    )


async def _dispatch_event(
    db: AsyncSession, gateway: BillingGateway, event: WebhookEvent
) -> list[TopUp]:
    """Act on a verified, first-seen Stripe event; returns the Top-ups it added. Must not commit."""
    syncs_subscriptions = _is_subscription_nudge(event)
    syncs_top_ups = event.type in _TOP_UP_NUDGES
    if not (syncs_subscriptions or syncs_top_ups):
        logger.info("Unhandled Stripe webhook event type: %s (event_id=%s)", event.type, event.id)
        return []
    customer_id = event.customer_id
    if customer_id is None and event.charge_id is not None:
        customer_id = await gateway.get_charge_customer(charge_id=event.charge_id)
    if customer_id is None:
        logger.error("Stripe %s event names no customer (event_id=%s)", event.type, event.id)
        return []
    user = await _locked_customer(db, customer_id=customer_id, event_id=event.id)
    if user is None:
        return []
    if syncs_subscriptions:
        await service.sync_customer(db, gateway, user_id=user.id, customer_id=customer_id)
    if syncs_top_ups:
        return await service.sync_top_ups(db, gateway, user_id=user.id, customer_id=customer_id)
    return []


async def _locked_customer(db: AsyncSession, *, customer_id: str, event_id: str) -> Optional[User]:
    """
    The customer's User, locked across the Stripe calls that follow, so webhooks for one
    customer run one after another and none can write an older state last.
    """
    user = await users_service.get_user_by_stripe_customer_id(db, customer_id)
    if user is None:
        logger.error(
            "Stripe webhook for unknown customer (event_id=%s, customer_id=%s)",
            event_id,
            customer_id,
        )
        return None
    await users_service.lock_user(db, user)
    return user
