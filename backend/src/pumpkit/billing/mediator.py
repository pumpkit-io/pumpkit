import hashlib
from dataclasses import asdict
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.auth.service.users as users_service
from pumpkit.auth.models import User
from pumpkit.billing import (
    coupon_operations,
    coupon_preview,
    coupon_redemption,
    coupon_service,
    service,
)
from pumpkit.billing.allowance import (
    SETTINGS_PAGE,
    limits,
    sells_top_ups,
    top_up_pack,
)
from pumpkit.billing.gateway import (
    BillingGateway,
    BillingProviderError,
    OneOffPrice,
    SubscriptionState,
    WebhookEvent,
    WebhookSignatureError,
)
from pumpkit.billing.models import Coupon, TopUp
from pumpkit.billing.schemas import (
    BillingMeResponse,
    BillingPortalResponse,
    BillingSubscriptionResponse,
    CheckoutRequest,
    CheckoutResponse,
    CouponPreviewResponse,
    CouponRedemptionRequest,
    CouponRedemptionResponse,
    FreeAccessCoverageResponse,
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
from pumpkit.core.rate_limit import hit_user_limit
from pumpkit.core.schemas import LinkToolResponse
from pumpkit.core.time import Clock, as_utc, system_clock


async def get_billing_me(
    db: AsyncSession, user: User, now: Optional[datetime] = None
) -> BillingMeResponse:
    """
    What the User holds and may do, from Pumpkit's copy only: never a call to
    the billing provider, so it reflects the last sync (ADR 0004).
    """
    moment = now or system_clock()
    entitlement = await service.get_entitlement(db, user_id=user.id, now=moment)
    subscription = entitlement.subscription
    offer = await service.get_subscription_offer(db, user_id=user.id, now=moment)
    free = entitlement.free_access
    if free and free.ends_at <= moment:
        free = None
    current = free.grant_at(moment) if free and free.starts_at <= moment else None
    pending_operations = await coupon_operations.pending(db, user_id=user.id)
    return BillingMeResponse(
        pending_coupon_operation=bool(pending_operations),
        pending_coupon_operation_id=pending_operations[0].operation_id
        if pending_operations
        else None,
        coupon_deferral=bool(free and subscription),
        free_access=FreeAccessCoverageResponse(
            months=free.months,
            starts_at=free.starts_at,
            ends_at=free.ends_at,
            current_starts_at=as_utc(current.starts_at) if current else None,
            current_ends_at=as_utc(current.ends_at) if current else None,
            queued_starts_at=free.starts_at
            if current is None
            else as_utc(current.ends_at)
            if as_utc(current.ends_at) < free.ends_at
            else None,
        )
        if free
        else None,
        subscription=(
            None
            if subscription is None
            else BillingSubscriptionResponse(
                status=subscription.status,
                plan_key=subscription.plan_key,
                current_period_end=as_utc(subscription.current_period_end)
                if subscription.current_period_end
                else None,
                cancel_at=as_utc(subscription.cancel_at) if subscription.cancel_at else None,
                paid_through=as_utc(subscription.paid_end)
                if subscription.paid_end and as_utc(subscription.paid_end) > moment
                else None,
            )
        ),
        subscribed=entitlement.subscribed,
        may_subscribe=offer.may_subscribe,
        trial_days=offer.trial_days,
    )


def subscription_link() -> LinkToolResponse:
    """Where the User manages their Subscription, unless the Instance sells no Plans."""
    if not service.sells_plans():
        return LinkToolResponse(
            message="This instance sells no plans: you can use all of Pumpkit without a "
            "subscription.",
            url=None,
        )
    url = settings.billing_page_url()
    return LinkToolResponse(
        message=f"Manage your subscription on the Settings page: {url}", url=url
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
        coupons_enabled=coupon_service.coupons_available(settings),
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
    key = settings.BILLING_TOP_UP_KEY if sells_top_ups() else None
    if key is None:
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
    acceptance: TermsAcceptanceRequest, refusal: str = "Accept the Terms to subscribe."
) -> None:
    """Raise unless the request ticks every box for the current Terms version."""
    if not (
        acceptance.accepted_terms
        and acceptance.requested_immediate_start
        and acceptance.approved_specific_clauses
        and acceptance.terms_version
    ):
        raise RefusedError(refusal)
    if acceptance.terms_version != TERMS_VERSION:
        raise ConflictError(
            "The Terms have changed. Please review the current Terms and accept them again."
        )


async def create_checkout_session(
    db: AsyncSession,
    gateway: BillingGateway,
    user: User,
    checkout_request: CheckoutRequest,
    clock: Clock = system_clock,
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
    user = await users_service.require_locked_user(db, user_id=user.id, clock=clock)
    await coupon_operations.require_settled(db, user_id=user.id)
    if await service.get_free_access(db, user_id=user.id, now=clock()):
        raise ConflictError(
            "Your free access is still running. Paid signup after free time is not available yet."
        )
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
    user = await users_service.require_locked_user(db, user_id=user.id, clock=clock)
    await coupon_operations.require_settled(db, user_id=user.id)
    await service.sync_customer(db, gateway, user_id=user.id, customer_id=customer_id)
    offer = await service.get_subscription_offer(db, user_id=user.id, now=clock())
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


async def _check_may_buy_top_up(db: AsyncSession, user: User, now: datetime) -> None:
    entitlement = await service.get_entitlement(db, user_id=user.id, now=now)
    if entitlement.may_buy_top_up:
        return
    subscription = entitlement.subscription
    status = subscription.status if subscription and entitlement.subscribed else None
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
    clock: Clock = system_clock,
) -> CheckoutResponse:
    """Current Free access or a paid-up Subscription qualifies; paid Terms precede Stripe.

    The normal webhook sync adds the pack only once paid.
    """
    user = await users_service.require_locked_user(db, user_id=user.id, clock=clock)
    await coupon_operations.require_settled(db, user_id=user.id)
    terms_apply = service.requires_terms_acceptance()
    if terms_apply:
        _require_terms_acceptance(checkout_request, "Accept the Terms to buy a top-up.")
    await _check_may_buy_top_up(db, user, clock())
    if terms_apply:
        await _record_terms_acceptance(db, user)

    price = await _top_up_price(gateway)
    if price is None:
        raise BillingProviderError("The configured Top-up has no active one-off price")
    user = await users_service.require_locked_user(db, user_id=user.id, clock=clock)
    await coupon_operations.require_settled(db, user_id=user.id)
    customer_id = await _ensure_stripe_customer(db, gateway, user)
    # First-customer creation commits, so deletion may have won the released User lock.
    user = await users_service.require_locked_user(db, user_id=user.id, clock=clock)
    await coupon_operations.require_settled(db, user_id=user.id)
    await _check_may_buy_top_up(db, user, clock())
    session = await gateway.create_top_up_checkout(
        customer_id=customer_id, price_id=price.price_id, user_id=user.id
    )
    await db.commit()
    return CheckoutResponse(url=session.url, session_id=session.id)


class FirstChargeFailed(RefusalError):
    """Subscribing now ended the Trial, but the provider couldn't charge the first period."""

    status_code = 402


class FirstChargeNeedsAuthentication(FirstChargeFailed):
    """The first charge waits for the User to authenticate it on the provider's page, `url`."""

    def __init__(self, detail: str, *, url: str) -> None:
        super().__init__(detail)
        self.url = url

    def response_body(self) -> dict[str, Any]:
        return {**super().response_body(), "code": "PAYMENT_NEEDS_AUTHENTICATION", "url": self.url}


async def subscribe_now(
    db: AsyncSession, gateway: BillingGateway, user: User, clock: Clock = system_clock
) -> BillingMeResponse:
    """Hold the User lock through immediate payment so accepted coupon intent cannot race it."""
    user = await users_service.require_locked_user(db, user_id=user.id, clock=clock)
    if not user.stripe_customer_id:
        raise _not_trialing()
    customer_id = user.stripe_customer_id
    await service.sync_customer(db, gateway, user_id=user.id, customer_id=customer_id)
    subscription = await service.get_user_subscription(db, user_id=user.id)
    await coupon_operations.require_settled(db, user_id=user.id)
    if await service.get_free_access(db, user_id=user.id, now=clock()):
        raise ConflictError("Your coupon free access must finish before any immediate payment.")
    if subscription is None or subscription.status != "trialing":
        # Keep the provider sync when refusing without releasing a lock before a mutation.
        await db.commit()
        raise _not_trialing()

    authentication_url = None
    provider_error = None
    try:
        authentication_url = await gateway.end_trial(
            subscription_id=subscription.stripe_subscription_id
        )
    except BillingProviderError as error:
        provider_error = error
    await users_service.lock_user(db, user)
    await service.sync_customer(db, gateway, user_id=user.id, customer_id=customer_id)
    await db.commit()
    if subscription.status == "active":
        return await get_billing_me(db, user)
    if provider_error is not None and subscription.status != "past_due":
        raise provider_error
    if authentication_url is not None:
        raise FirstChargeNeedsAuthentication(
            "Your trial has ended, but your bank needs you to confirm the first payment. "
            "Confirm it on Stripe's invoice page.",
            url=authentication_url,
        )
    raise FirstChargeFailed(
        "Your trial has ended, but the first payment didn't go through. "
        "Open billing to complete or update your payment.",
        fix_page=BILLING_PAGE,
    )


def _not_trialing() -> ConflictError:
    return ConflictError("You're not in a trial, so there's no trial to end.")


async def create_billing_portal_session(
    db: AsyncSession,
    gateway: BillingGateway,
    user: User,
    clock: Clock = system_clock,
) -> BillingPortalResponse:
    user = await users_service.require_locked_user(db, user_id=user.id, clock=clock)
    await coupon_operations.require_settled(db, user_id=user.id)
    customer_id = await _ensure_stripe_customer(db, gateway, user)
    user = await users_service.require_locked_user(db, user_id=user.id, clock=clock)
    await coupon_operations.require_settled(db, user_id=user.id)
    if await service.get_free_access(db, user_id=user.id, now=clock()):
        raise ConflictError(
            "Use Cancel renewal to keep your paid and free time. Other subscription changes are unavailable until free access ends."
        )
    url = await gateway.create_portal_url(customer_id=customer_id)
    return BillingPortalResponse(url=url)


async def handle_webhook(
    db: AsyncSession,
    gateway: BillingGateway,
    payload: bytes,
    signature: Optional[str],
    now: datetime,
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
        added = await _dispatch_event(db, gateway, event, now=now)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    for top_up in added:
        if as_utc(top_up.expires_at) > now:
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
    db: AsyncSession, gateway: BillingGateway, event: WebhookEvent, *, now: datetime
) -> list[TopUp]:
    """
    Act on a verified, first-seen Stripe event; returns the Top-ups it added not already removed.
    Must not commit.
    """
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
        for operation in await coupon_operations.pending(db, user_id=user.id):
            await coupon_operations.reconcile(
                db, gateway, user=user, operation=operation, now=now, mutate=False
            )
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


async def preview_coupon(
    db: AsyncSession, gateway: BillingGateway, user: User, *, code: str, now: datetime
) -> CouponPreviewResponse:
    if not coupon_service.coupons_available(settings):
        raise RefusedError("Coupons are unavailable on this instance.")
    hit_user_limit("check coupon", user.id, "10/minute")
    try:
        coupon_service.validate_offers(
            await gateway.list_plans(settings.BILLING_PLAN_KEYS), config=settings
        )
    except coupon_service.CouponCommandError as exc:
        raise ConflictError(
            "The coupon offer is unavailable. Try again later or contact its sender."
        ) from exc
    if user.stripe_customer_id and await gateway.has_pending_checkout(
        customer_id=user.stripe_customer_id
    ):
        raise ConflictError(
            "You have a pending paid checkout. Finish it, let it expire, or contact support to cancel it before using a coupon."
        )
    if user.stripe_customer_id and await gateway.has_unsettled_invoices(
        customer_id=user.stripe_customer_id
    ):
        raise ConflictError(
            "Resolve your outstanding or processing payment in the billing portal before using a coupon."
        )
    subscriptions = (
        await gateway.list_subscriptions(customer_id=user.stripe_customer_id)
        if user.stripe_customer_id
        else []
    )
    return await coupon_preview.preview(
        db, user=user, subscriptions=subscriptions, now=now, code=code
    )


async def redeem_coupon(
    db: AsyncSession,
    gateway: BillingGateway,
    user: User,
    *,
    request: CouponRedemptionRequest,
    clock: Clock,
) -> CouponRedemptionResponse:
    user = await users_service.require_locked_user(db, user_id=user.id, clock=clock)
    operation = await coupon_operations.find(db, user_id=user.id, operation_id=request.operation_id)
    if operation is not None:
        if (
            operation.revision_digest
            != hashlib.sha256(request.revision.get_secret_value().encode()).hexdigest()
        ):
            raise ConflictError(
                "This operation was used for another coupon offer. Check its result."
            )
        response = await coupon_operations.reconcile(
            db, gateway, user=user, operation=operation, now=clock()
        )
        await db.commit()
        return response
    await coupon_operations.require_settled(db, user_id=user.id)
    existing = await coupon_redemption.find_result(
        db, user_id=user.id, operation_id=request.operation_id
    )
    if existing is not None:
        if (
            existing.revision_digest
            != hashlib.sha256(request.revision.get_secret_value().encode()).hexdigest()
        ):
            raise ConflictError(
                "This operation was used for another coupon offer. Check its result."
            )
        return coupon_redemption.result(existing)
    signed = coupon_redemption.decode(
        request.revision.get_secret_value(), user_id=user.id, now=clock()
    )
    coupon = await coupon_redemption.lock_coupon(db, signed.coupon_id)
    current, subscriptions = await _preview_locked_coupon(
        db, gateway, user, coupon=coupon, clock=clock
    )
    signed = coupon_redemption.decode(
        request.revision.get_secret_value(), user_id=user.id, now=clock()
    )
    current_signed = coupon_redemption.decode(current.revision, user_id=user.id, now=clock())
    if signed.state != current_signed.state:
        raise ConflictError("The coupon offer has changed. Check the code and review it again.")
    coupon_redemption.require_same_offer(signed, current, request)
    if current.next_payment_at is not None:
        assert user.stripe_customer_id is not None
        state = await coupon_operations.monthly_state(
            db,
            user_id=user.id,
            subscriptions=subscriptions,
            now=clock(),
        )
        assert state is not None
        operation = await coupon_operations.prepare(
            db,
            user=user,
            coupon=coupon,
            offer=current,
            request=request,
            state=state,
            now=current_signed.issued_at,
        )
        # Accepted intent and its reservation must survive a lost provider response or process crash.
        await db.commit()
        user = await users_service.require_locked_user(db, user_id=user.id, clock=clock)
        response = await coupon_operations.reconcile(
            db, gateway, user=user, operation=operation, now=clock()
        )
        await db.commit()
        return response
    access = await coupon_redemption.grant(
        db, user=user, coupon=coupon, offer=current, request=request, now=current_signed.issued_at
    )
    response = coupon_redemption.result(access)
    await db.commit()
    return response


async def _preview_locked_coupon(
    db: AsyncSession, gateway: BillingGateway, user: User, *, coupon: Coupon, clock: Clock
) -> tuple[CouponPreviewResponse, list[SubscriptionState]]:
    if not coupon_service.coupons_available(settings):
        raise RefusedError("Coupons are unavailable on this instance.")
    try:
        coupon_service.validate_offers(
            await gateway.list_plans(settings.BILLING_PLAN_KEYS), config=settings
        )
    except coupon_service.CouponCommandError as exc:
        raise ConflictError("The coupon offer is unavailable. Try again later.") from exc
    if user.stripe_customer_id and await gateway.has_pending_checkout(
        customer_id=user.stripe_customer_id
    ):
        raise ConflictError(
            "You have a pending paid checkout. Finish it, let it expire, or contact support to cancel it before using a coupon."
        )
    if user.stripe_customer_id and await gateway.has_unsettled_invoices(
        customer_id=user.stripe_customer_id
    ):
        raise ConflictError("Resolve your outstanding or processing payment before using a coupon.")
    subscriptions = (
        await gateway.list_subscriptions(customer_id=user.stripe_customer_id)
        if user.stripe_customer_id
        else []
    )
    if user.stripe_customer_id:
        await service.sync_customer(
            db, gateway, user_id=user.id, customer_id=user.stripe_customer_id
        )
    return await coupon_preview.preview(
        db, user=user, subscriptions=subscriptions, now=clock(), coupon=coupon
    ), subscriptions


async def lookup_coupon_redemption(
    db: AsyncSession, gateway: BillingGateway, user: User, *, operation_id: str, clock: Clock
) -> CouponRedemptionResponse:
    user = await users_service.require_locked_user(db, user_id=user.id, clock=clock)
    operation = await coupon_operations.find(db, user_id=user.id, operation_id=operation_id)
    if operation is None:
        return await coupon_redemption.lookup(db, user_id=user.id, operation_id=operation_id)
    response = await coupon_operations.reconcile(
        db, gateway, user=user, operation=operation, now=clock()
    )
    await db.commit()
    return response


async def cancel_renewal(
    db: AsyncSession, gateway: BillingGateway, user: User, *, clock: Clock
) -> BillingMeResponse:
    user = await users_service.require_locked_user(db, user_id=user.id, clock=clock)
    await coupon_operations.require_settled(db, user_id=user.id)
    free = await service.get_free_access(db, user_id=user.id, now=clock())
    if not free or not user.stripe_customer_id:
        raise ConflictError("Manage your subscription in billing.")
    await service.sync_customer(db, gateway, user_id=user.id, customer_id=user.stripe_customer_id)
    subscription = await service.get_user_subscription(db, user_id=user.id)
    if subscription is None:
        raise ConflictError("Your subscription has already ended.")
    if not subscription.cancel_at:
        await gateway.cancel_renewal(
            subscription_id=subscription.stripe_subscription_id, ends_at=as_utc(free.ends_at)
        )
        await service.sync_customer(
            db, gateway, user_id=user.id, customer_id=user.stripe_customer_id
        )
    await db.commit()
    return await get_billing_me(db, user, now=clock())
