import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Optional

from itsdangerous import BadData, URLSafeSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.billing import coupon_operations, coupon_service, service
from pumpkit.billing.gateway import (
    BillingGateway,
    BillingProviderError,
    DeferralRefused,
    SubscriptionState,
)
from pumpkit.billing.models import PlanChange, Subscription
from pumpkit.billing.schemas import (
    FuturePlanResponse,
    PlanChangePreviewResponse,
    PlanChangeRequest,
    PlanChangeResponse,
)
from pumpkit.core.config import settings
from pumpkit.core.errors import ConflictError, NotFoundError, RefusedError
from pumpkit.core.time import Clock, as_utc


def snapshot(state: SubscriptionState) -> dict:
    return json.loads(json.dumps(asdict(state), default=lambda value: value.isoformat()))


async def pending(db: AsyncSession, *, user_id: Optional[str] = None) -> list[PlanChange]:
    query = select(PlanChange).where(PlanChange.status == "pending")
    if user_id is not None:
        query = query.where(PlanChange.user_id == user_id)
    return list(await db.scalars(query.order_by(PlanChange.created_at, PlanChange.id)))


async def find(db: AsyncSession, *, user_id: str, operation_id: str) -> PlanChange:
    operation = await db.scalar(
        select(PlanChange)
        .where(PlanChange.user_id == user_id, PlanChange.operation_id == operation_id)
        .execution_options(populate_existing=True)
    )
    if operation is None:
        raise NotFoundError("No plan change was found for this operation.")
    return operation


def response(operation: PlanChange) -> PlanChangeResponse:
    return PlanChangeResponse(
        **FuturePlanResponse.model_validate(operation.offer).model_dump(),
        operation_id=operation.operation_id,
        status=operation.status,
        detail=operation.detail,
    )


async def future_plan(
    db: AsyncSession, *, subscription: Subscription, ends_at: datetime
) -> Optional[FuturePlanResponse]:
    if not subscription.stripe_price_id:
        return None
    operation = await db.scalar(
        select(PlanChange)
        .where(
            PlanChange.user_id == subscription.user_id,
            PlanChange.subscription_id == subscription.stripe_subscription_id,
            PlanChange.status == "completed",
            PlanChange.offer["price_id"].as_string() == subscription.stripe_price_id,
        )
        .order_by(PlanChange.created_at.desc(), PlanChange.id.desc())
        .limit(1)
    )
    if operation:
        return FuturePlanResponse.model_validate({**operation.offer, "first_payment_at": ends_at})
    return None


async def current_state(
    db: AsyncSession, gateway: BillingGateway, *, user: User, now: datetime
) -> SubscriptionState:
    if not user.stripe_customer_id:
        raise ConflictError("Arrange a subscription before changing billing frequency.")
    if await gateway.has_pending_checkout(
        customer_id=user.stripe_customer_id
    ) or await gateway.has_unsettled_invoices(customer_id=user.stripe_customer_id):
        raise ConflictError(
            "Resolve your pending checkout or payment before changing billing frequency."
        )
    states = await service.sync_customer(
        db, gateway, user_id=user.id, customer_id=user.stripe_customer_id
    )
    state = await coupon_operations.deferrable_state(
        db, user_id=user.id, subscriptions=states, now=now
    )
    free = await service.get_free_access(db, user_id=user.id, now=now)
    if (
        not state
        or not free
        or state.latest_invoice_status not in {None, "paid", "void"}
        or state.status != "trialing"
        or state.cancel_at
        or not state.trial_end
        or as_utc(state.trial_end) != as_utc(free.ends_at)
        or as_utc(state.trial_end) <= now
    ):
        raise ConflictError(
            "Billing frequency can change only for a renewing subscription after its remaining free time."
        )
    return state


async def preview(
    db: AsyncSession, gateway: BillingGateway, *, user: User, plan_key: str, now: datetime
) -> PlanChangePreviewResponse:
    if not coupon_service.coupons_available(settings):
        raise RefusedError(
            "Billing frequency changes during free access are unavailable on this instance."
        )
    await coupon_operations.require_settled(db, user_id=user.id)
    state = await current_state(db, gateway, user=user, now=now)
    plans = await gateway.list_plans(settings.BILLING_PLAN_KEYS)
    try:
        coupon_service.validate_offers(plans, config=settings)
    except coupon_service.CouponCommandError as exc:
        raise ConflictError("The configured plans are unavailable. Contact support.") from exc
    plan = next((p for p in plans if p.key == plan_key), None)
    if (
        plan is None
        or plan.interval == state.interval
        or plan.interval not in {"month", "year"}
        or plan.interval_count != 1
    ):
        raise ConflictError("Choose the other monthly or annual plan.")
    assert state.trial_end is not None
    offer = PlanChangePreviewResponse(
        plan_key=plan.key,
        product_name=plan.product_name,
        amount=plan.amount,
        currency=plan.currency,
        interval=plan.interval,
        interval_count=plan.interval_count,
        first_payment_at=as_utc(state.trial_end),
        revision="",
    )
    offer.revision = URLSafeSerializer(settings.JWT_SECRET_KEY, salt="plan-change").dumps(
        {
            "user_id": user.id,
            "expires_at": (now + timedelta(minutes=10)).isoformat(),
            "original": snapshot(state),
            "offer": offer.model_dump(mode="json", exclude={"revision"}),
            "price_id": plan.price_id,
        }
    )
    return offer


async def prepare(
    db: AsyncSession,
    gateway: BillingGateway,
    *,
    user: User,
    request: PlanChangeRequest,
    now: datetime,
) -> PlanChange:
    try:
        signed = URLSafeSerializer(settings.JWT_SECRET_KEY, salt="plan-change").loads(
            request.revision.get_secret_value()
        )
        if (
            signed["user_id"] != user.id
            or as_utc(datetime.fromisoformat(signed["expires_at"])) <= now
        ):
            raise ValueError
        offer = PlanChangePreviewResponse.model_validate({**signed["offer"], "revision": ""})
    except (BadData, ValueError, TypeError, KeyError) as exc:
        raise ConflictError("This plan offer has expired. Review it again.") from exc
    current = await preview(db, gateway, user=user, plan_key=offer.plan_key, now=now)
    current_signed = URLSafeSerializer(settings.JWT_SECRET_KEY, salt="plan-change").loads(
        current.revision
    )
    if (
        signed["original"] != current_signed["original"]
        or signed["price_id"] != current_signed["price_id"]
        or signed["offer"] != current_signed["offer"]
    ):
        raise ConflictError("Your plan or payment date has changed. Review the offer again.")
    assert user.stripe_customer_id is not None
    operation = PlanChange(
        user_id=user.id,
        operation_id=request.operation_id,
        revision_digest=hashlib.sha256(request.revision.get_secret_value().encode()).hexdigest(),
        status="pending",
        customer_id=user.stripe_customer_id,
        subscription_id=signed["original"]["id"],
        original=signed["original"],
        offer={**signed["offer"], "price_id": signed["price_id"], "preserve_payment_date": True},
        created_at=now,
    )
    db.add(operation)
    await db.flush()
    return operation


def refuse(operation: PlanChange, *, now: datetime) -> PlanChangeResponse:
    operation.status = "refused"
    operation.resolved_at = now
    operation.detail = "No plan change was sent. Review your current plan and payment date again."
    return response(operation)


async def reconcile(
    db: AsyncSession,
    gateway: BillingGateway,
    *,
    user: User,
    operation: PlanChange,
    clock: Clock,
    dispatch: bool = False,
    mutate: bool = True,
    prior_unknown: bool = True,
) -> PlanChangeResponse:
    if operation.status != "pending":
        return response(operation)
    operation.detail = "Your billing frequency change is being confirmed. Retry its status before changing billing."
    try:
        states = await service.sync_customer(
            db, gateway, user_id=user.id, customer_id=operation.customer_id
        )
        state = next((s for s in states if s.id == operation.subscription_id), None)
        if (
            state is None
            or user.stripe_customer_id != operation.customer_id
            or len([s for s in states if s.status not in {"canceled", "incomplete_expired"}]) != 1
        ):
            return response(operation)
        original = operation.original
        applied = (
            state.plan_change_operation == operation.id
            and state.price_id == operation.offer["price_id"]
            and state.interval == operation.offer["interval"]
        )
        retained = (
            state.item_id == original["item_id"]
            and state.item_count == 1
            and state.interval_count == 1
            and state.billing_mode == original["billing_mode"]
            and not state.has_pending_update
            and not state.schedule_id
            and not state.paused
            and state.trial_end is not None
            and state.trial_end.isoformat() == original["trial_end"]
            and state.billing_cycle_anchor is not None
            and state.billing_cycle_anchor.isoformat() == original["billing_cycle_anchor"]
            and state.coupon_operation == original["coupon_operation"]
            and state.paid_signup_operation == original["paid_signup_operation"]
        )
        if applied and retained:
            operation.status = "completed"
            operation.resolved_at = clock()
            operation.detail = None
            return response(operation)
        unchanged = snapshot(state) == original and state.cancel_at is None
        valid = (
            unchanged
            and state.status == "trialing"
            and state.trial_end is not None
            and clock() < as_utc(state.trial_end)
        )
        if not valid:
            return (
                refuse(operation, now=clock())
                if operation.attempted_at is None
                else response(operation)
            )
        if not mutate or not dispatch:
            return response(operation)
        if await gateway.has_pending_checkout(
            customer_id=operation.customer_id
        ) or await gateway.has_unsettled_invoices(customer_id=operation.customer_id):
            return response(operation)
        assert state.trial_end is not None
        # Check the original retention deadline after provider reads, immediately before replay.
        if (
            operation.attempted_at is None
            or clock() >= as_utc(operation.attempted_at) + timedelta(hours=23)
            or clock() >= as_utc(state.trial_end)
        ):
            return response(operation)
        try:
            await gateway.change_plan(
                subscription_id=operation.subscription_id,
                item_id=original["item_id"],
                price_id=operation.offer["price_id"],
                operation_id=operation.id,
                # Older intents must replay their original parameters under the same key.
                first_payment_at=(
                    as_utc(datetime.fromisoformat(operation.offer["first_payment_at"]))
                    if operation.offer.get("preserve_payment_date", False)
                    else None
                ),
            )
        except DeferralRefused:
            if not prior_unknown:
                return refuse(operation, now=clock())
            return response(operation)
        return await reconcile(
            db, gateway, user=user, operation=operation, clock=clock, mutate=False
        )
    except BillingProviderError:
        return response(operation)
