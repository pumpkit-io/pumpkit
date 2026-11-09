import hashlib
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Optional

from itsdangerous import BadData, URLSafeSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.billing import coupon_service, service
from pumpkit.billing.allowance import limits
from pumpkit.billing.gateway import (
    BillingGateway,
    BillingProviderError,
    DeferralRefused,
    SubscriptionState,
)
from pumpkit.billing.models import CouponOperation, PaidSignup
from pumpkit.billing.schemas import PaidSignupPreviewResponse, PaidSignupRequest, PaidSignupResponse
from pumpkit.billing.terms import TERMS_VERSION
from pumpkit.core.config import settings
from pumpkit.core.errors import ConflictError, NotFoundError, RefusedError
from pumpkit.core.time import Clock, as_utc


async def pending(db: AsyncSession, *, user_id: Optional[str] = None) -> list[PaidSignup]:
    query = select(PaidSignup).where(PaidSignup.status == "pending")
    if user_id is not None:
        query = query.where(PaidSignup.user_id == user_id)
    return list(await db.scalars(query.order_by(PaidSignup.id)))


async def find(db: AsyncSession, *, user_id: str, operation_id: str) -> PaidSignup:
    operation = await db.scalar(
        select(PaidSignup)
        .where(PaidSignup.user_id == user_id, PaidSignup.operation_id == operation_id)
        .execution_options(populate_existing=True)
    )
    if operation is None:
        raise NotFoundError("No paid signup was found for this operation.")
    return operation


def response(operation: PaidSignup, *, url: Optional[str] = None) -> PaidSignupResponse:
    return PaidSignupResponse(
        operation_id=operation.operation_id,
        status=operation.status,
        detail=operation.detail,
        url=url,
        session_id=operation.session_id,
        first_payment_at=datetime.fromisoformat(operation.offer["first_payment_at"]),
        plan_key=operation.offer["plan_key"],
    )


async def preview(
    db: AsyncSession, gateway: BillingGateway, *, user: User, plan_key: str, now: datetime
) -> PaidSignupPreviewResponse:
    if not coupon_service.coupons_available(settings):
        raise RefusedError("Paid signup during free access is unavailable on this instance.")
    if await pending(db, user_id=user.id) or await db.scalar(
        select(CouponOperation.id).where(
            CouponOperation.user_id == user.id, CouponOperation.status == "pending"
        )
    ):
        raise ConflictError("Resolve your pending billing operation before arranging paid renewal.")
    free = await service.get_free_access_coverage(db, user_id=user.id)
    if not free or not as_utc(free.starts_at) <= now < as_utc(free.ends_at):
        raise ConflictError("Review a new paid offer after your free access ends.")
    if as_utc(free.ends_at).microsecond:
        raise ConflictError(
            "This existing free access date cannot be represented exactly by billing. Contact support; all free access is unchanged."
        )
    if as_utc(free.ends_at) > now + timedelta(days=730):
        raise ConflictError("The future payment date exceeds the supported limit.")
    await require_provider_ready(gateway, user=user)
    plans = await gateway.list_plans(settings.BILLING_PLAN_KEYS)
    plan = next((p for p in plans if p.key == plan_key), None)
    if plan is None or plan.interval not in {"month", "year"} or plan.interval_count != 1:
        raise ConflictError("This plan is unavailable. Review the current plans.")
    offer = PaidSignupPreviewResponse(
        plan_key=plan.key,
        product_name=plan.product_name,
        amount=plan.amount,
        currency=plan.currency,
        interval=plan.interval,
        interval_count=plan.interval_count,
        first_payment_at=as_utc(free.ends_at),
        terms_version=TERMS_VERSION if service.requires_terms_acceptance() else None,
        revision="",
    )
    payload = {
        "user_id": user.id,
        "offer": offer.model_dump(mode="json", exclude={"revision"}),
        "price_id": plan.price_id,
        "expires_at": (now + timedelta(minutes=10)).isoformat(),
    }
    offer.revision = URLSafeSerializer(settings.JWT_SECRET_KEY, salt="paid-signup").dumps(payload)
    return offer


async def require_provider_ready(gateway: BillingGateway, *, user: User) -> None:
    if not user.stripe_customer_id:
        return
    states = await gateway.list_subscriptions(customer_id=user.stripe_customer_id)
    if any(s.status not in {"canceled", "incomplete_expired"} for s in states):
        raise ConflictError("Resolve your existing subscription before arranging paid renewal.")
    if await gateway.has_pending_checkout(
        customer_id=user.stripe_customer_id
    ) or await gateway.has_unsettled_invoices(customer_id=user.stripe_customer_id):
        raise ConflictError(
            "Resolve your pending checkout or payment before arranging paid renewal."
        )


async def prepare(
    db: AsyncSession,
    gateway: BillingGateway,
    *,
    user: User,
    request: PaidSignupRequest,
    now: datetime,
) -> PaidSignup:
    try:
        signed = URLSafeSerializer(settings.JWT_SECRET_KEY, salt="paid-signup").loads(
            request.revision.get_secret_value()
        )
        if (
            signed["user_id"] != user.id
            or as_utc(datetime.fromisoformat(signed["expires_at"])) <= now
        ):
            raise ValueError
        offer = PaidSignupPreviewResponse.model_validate({**signed["offer"], "revision": ""})
    except (BadData, ValueError, TypeError, KeyError) as exc:
        raise ConflictError(
            "This paid offer has expired. Review the plan and payment date again."
        ) from exc
    current = await preview(db, gateway, user=user, plan_key=offer.plan_key, now=now)
    if current.model_dump(exclude={"revision"}) != offer.model_dump(exclude={"revision"}):
        raise ConflictError("The plan or first payment date has changed. Review it again.")
    plans = await gateway.list_plans([offer.plan_key])
    if not any(p.price_id == signed["price_id"] for p in plans):
        raise ConflictError("The plan price has changed. Review it again.")
    if request.terms_version != offer.terms_version:
        raise ConflictError("The Terms have changed. Review them again.")
    if offer.terms_version and not (
        request.accepted_terms
        and request.requested_immediate_start
        and request.approved_specific_clauses
    ):
        raise RefusedError("Accept the paid Terms and all three requests before arranging renewal.")
    acceptance = request.model_dump(mode="json", exclude={"revision", "operation_id"})
    acceptance["accepted_at"] = now.isoformat()
    operation = PaidSignup(
        user_id=user.id,
        operation_id=request.operation_id,
        revision_digest=hashlib.sha256(request.revision.get_secret_value().encode()).hexdigest(),
        status="pending",
        customer_id=user.stripe_customer_id,
        offer={
            **offer.model_dump(mode="json", exclude={"revision"}),
            "price_id": signed["price_id"],
            "checkout_expires_at": (now + timedelta(hours=24)).isoformat(),
        },
        acceptance=acceptance,
        first_payment_at=offer.first_payment_at,
        created_at=now,
    )
    db.add(operation)
    if offer.terms_version:
        await service.record_terms_acceptance(
            db,
            user_id=user.id,
            terms_version=offer.terms_version,
            accepted_terms=True,
            requested_immediate_start=True,
            approved_specific_clauses=True,
            paid_offer={
                **offer.model_dump(mode="json", exclude={"revision"}),
                "price_id": signed["price_id"],
                "language": request.language,
            },
        )
    await db.flush()
    return operation


def refuse(operation: PaidSignup, *, now: datetime, detail: str) -> PaidSignupResponse:
    operation.status = "refused"
    operation.resolved_at = now
    operation.detail = detail
    return response(operation)


async def reconcile(
    db: AsyncSession,
    gateway: BillingGateway,
    *,
    user: User,
    operation: PaidSignup,
    clock: Clock,
    cancel: bool = False,
    mutate: bool = True,
    dispatch: bool = False,
    prior_unknown: bool = False,
) -> PaidSignupResponse:
    now = clock()
    if operation.status != "pending" and not (
        cancel and operation.status == "completed" and now < as_utc(operation.first_payment_at)
    ):
        return response(operation)
    cancel = cancel or operation.cancel_requested_at is not None
    customer_id = operation.customer_id
    if not customer_id or customer_id != user.stripe_customer_id:
        raise ConflictError("Your paid signup customer is being confirmed. Retry its status.")
    sent = False
    try:
        states = await service.sync_customer(db, gateway, user_id=user.id, customer_id=customer_id)
        now = clock()
        attributed = [s for s in states if s.paid_signup_operation == operation.id]
        if len(attributed) > 1:
            operation.detail = (
                "Multiple subscriptions need support review before billing can continue."
            )
            return response(operation)
        if attributed:
            state = attributed[0]
            operation.subscription_id = state.id
            target = as_utc(datetime.fromisoformat(operation.offer["first_payment_at"]))
            if (
                state.price_id != operation.offer["price_id"]
                or state.plan_key != operation.offer["plan_key"]
                or not state.trial_end
                or as_utc(state.trial_end) != target
                or state.interval != operation.offer["interval"]
                or state.interval_count != 1
            ):
                operation.detail = (
                    "The provider plan differs from the accepted offer. Contact support."
                )
                return response(operation)
            operation.creation_state = "confirmed"
            if cancel or state.status in {"canceled", "incomplete_expired"}:
                await _preserve_settled_paid_coverage(
                    db,
                    user=user,
                    state=state,
                    clock=clock,
                    target=target,
                )
            if state.status in {"canceled", "incomplete_expired"}:
                return refuse(
                    operation,
                    now=clock(),
                    detail="This subscription has ended. No future renewal is arranged.",
                )
            if not cancel and state.status not in {"active", "trialing", "past_due"}:
                operation.detail = (
                    "Your subscription needs billing review before renewal can be confirmed."
                )
                return response(operation)
            if cancel and state.status not in {"canceled", "incomplete_expired"}:
                await gateway.cancel_subscription(subscription_id=state.id)
                states = await service.sync_customer(
                    db, gateway, user_id=user.id, customer_id=customer_id
                )
                final = next((s for s in states if s.id == state.id), None)
                now = clock()
                if (
                    final is None
                    or final.status not in {"canceled", "incomplete_expired"}
                    or final.paid_signup_operation != operation.id
                    or final.price_id != operation.offer["price_id"]
                    or final.plan_key != operation.offer["plan_key"]
                    or final.trial_end is None
                    or as_utc(final.trial_end) != target
                    or final.interval != operation.offer["interval"]
                    or final.interval_count != 1
                ):
                    operation.detail = "Your cancellation is being confirmed. Check signup again."
                    return response(operation)
                await _preserve_settled_paid_coverage(
                    db, user=user, state=final, clock=clock, target=target
                )
            operation.status = "refused" if cancel else "completed"
            operation.resolved_at = clock()
            operation.detail = (
                "Paid signup cancelled. Your free access is unchanged." if cancel else None
            )
            await db.flush()
            return response(operation)
        if any(s.status not in {"canceled", "incomplete_expired"} for s in states):
            operation.detail = "Another subscription needs review. Your free access is unchanged."
            return response(operation)
        setups = [
            s
            for s in await gateway.list_paid_signup_setups(customer_id=customer_id)
            if s.operation_id == operation.id
        ]
        if len(setups) > 1:
            operation.detail = (
                "Multiple setup checkouts need review. Your free access is unchanged."
            )
            return response(operation)
        now = clock()
        setup = setups[0] if setups else None
        if setup:
            operation.session_id = setup.id
        target = as_utc(datetime.fromisoformat(operation.offer["first_payment_at"]))
        if operation.creation_state in {"uncertain", "acknowledged"} and not dispatch:
            if cancel or target <= now:
                operation.cancel_requested_at = operation.cancel_requested_at or now
                operation.detail = "Your cancellation is not confirmed yet. Check its status again; billing changes and account deletion will be available when confirmation finishes."
            else:
                operation.detail = "Your subscription request is being confirmed. Its agreed plan and payment date stay unchanged."
            return response(operation)
        if cancel or target <= now:
            if setup and setup.status == "open":
                if not mutate:
                    return response(operation)
                await gateway.expire_paid_signup_setup(session_id=setup.id)
                return await reconcile(
                    db,
                    gateway,
                    user=user,
                    operation=operation,
                    clock=clock,
                    cancel=True,
                    mutate=False,
                )
            return refuse(
                operation,
                now=now,
                detail="No future payment was arranged. Review a fresh paid offer to subscribe."
                if target <= now
                else "Paid signup cancelled. Your free access is unchanged.",
            )
        free = await service.get_free_access_coverage(db, user_id=user.id)
        if not free or as_utc(free.ends_at) != target:
            operation.detail = (
                "Your free access changed. Cancel this signup and review the new payment date."
            )
            return response(operation)
        if not mutate:
            return response(operation)
        if setup is None:
            await require_provider_ready(gateway, user=user)
            expiry = as_utc(datetime.fromisoformat(operation.offer["checkout_expires_at"]))
            if expiry < now + timedelta(minutes=30):
                return refuse(
                    operation,
                    now=now,
                    detail="Checkout expired. Review a fresh paid offer; all free access is unchanged.",
                )
            setup = await gateway.create_paid_signup_setup(
                customer_id=customer_id,
                user_id=user.id,
                operation_id=operation.id,
                currency=operation.offer["currency"],
                expires_at=expiry,
            )
            operation.session_id = setup.id
        if setup.status == "expired" or setup.setup_status == "canceled":
            return refuse(
                operation,
                now=now,
                detail="Checkout expired or was cancelled. Your free access is unchanged.",
            )
        if setup.status == "open":
            operation.detail = "Complete checkout to arrange future payment, or cancel this signup."
            return response(operation, url=setup.url)
        if not (
            setup.status == "complete"
            and setup.setup_status == "succeeded"
            and setup.payment_method_id
            and setup.setup_customer_id == customer_id
            and setup.payment_method_customer_id == customer_id
            and setup.usage == "off_session"
            and (not dispatch or setup.payment_method_id == operation.payment_method_id)
        ):
            operation.detail = (
                "Your payment setup is being confirmed. Your free access is unchanged."
            )
            return response(operation)
        if await gateway.has_pending_checkout(
            customer_id=customer_id
        ) or await gateway.has_unsettled_invoices(customer_id=customer_id):
            operation.detail = "Resolve the pending payment before paid signup can finish."
            return response(operation)
        now = clock()
        if target <= now:
            return await reconcile(db, gateway, user=user, operation=operation, clock=clock)
        if not dispatch:
            operation.payment_method_id = setup.payment_method_id
            operation.creation_state = "ready"
            operation.detail = "Your accepted subscription is ready to be arranged."
            return response(operation)
        if prior_unknown and (
            operation.creation_attempted_at is None
            or clock() >= as_utc(operation.creation_attempted_at) + timedelta(hours=23)
        ):
            operation.detail = "Your subscription is still being confirmed. Check its status again or contact support."
            return response(operation)
        sent = True
        await gateway.create_paid_signup(
            customer_id=customer_id,
            price_id=operation.offer["price_id"],
            payment_method_id=setup.payment_method_id,
            operation_id=operation.id,
            first_payment_at=target,
        )
        operation.creation_state = "acknowledged"
        return await reconcile(
            db, gateway, user=user, operation=operation, clock=clock, mutate=False
        )
    except DeferralRefused:
        operation.creation_state = "uncertain" if prior_unknown else "refused"
        operation.detail = (
            "The earlier signup outcome is still being confirmed. A retry was refused; check again or contact support."
            if prior_unknown
            else "The provider refused the exact agreed payment date. Your free access is unchanged; cancel this signup to review a fresh offer."
        )
        return response(operation)
    except BillingProviderError:
        operation.detail = (
            "Your paid signup is being confirmed. Retry its status; your free access is unchanged."
        )
        return response(operation)

    finally:
        if dispatch and not prior_unknown and not sent and operation.creation_state == "uncertain":
            operation.creation_state = "not_started"


async def _preserve_settled_paid_coverage(
    db: AsyncSession,
    *,
    user: User,
    state: SubscriptionState,
    clock: Clock,
    target: datetime,
) -> None:
    subscription = await service.get_subscription_by_stripe_id(db, state.id)
    now = clock()
    if not (
        state.paid_current_period
        and state.current_period_start
        and state.current_period_end
        and state.billing_cycle_anchor
        and target <= as_utc(state.current_period_start) <= now < as_utc(state.current_period_end)
    ):
        return
    if subscription is None or subscription.user_id != user.id:
        raise ConflictError("Your paid coverage is being confirmed. Check signup again.")
    if (
        subscription.paid_start
        and subscription.paid_end
        and subscription.paid_anchor
        and subscription.paid_allowance
        and as_utc(subscription.paid_start) == as_utc(state.current_period_start)
        and as_utc(subscription.paid_end) == as_utc(state.current_period_end)
        and as_utc(subscription.paid_anchor) == as_utc(state.billing_cycle_anchor)
    ):
        return
    subscription.preserved_trial = False
    subscription.paid_start = state.current_period_start
    subscription.paid_end = state.current_period_end
    subscription.paid_anchor = state.billing_cycle_anchor
    subscription.paid_allowance = asdict(limits(trial=False))
    await db.flush()
