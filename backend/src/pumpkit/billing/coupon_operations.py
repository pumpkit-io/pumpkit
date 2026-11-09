import hashlib
from dataclasses import asdict
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.billing import coupon_redemption, coupon_service, service
from pumpkit.billing.allowance import limits, paid_period
from pumpkit.billing.gateway import (
    BillingGateway,
    BillingProviderError,
    DeferralRefused,
    SubscriptionState,
)
from pumpkit.billing.models import Coupon, CouponClaim, CouponHistory, CouponOperation, FreeAccess
from pumpkit.billing.schemas import (
    CouponPreviewResponse,
    CouponRedemptionRequest,
    CouponRedemptionResponse,
)
from pumpkit.core.config import settings
from pumpkit.core.errors import ConflictError
from pumpkit.core.time import as_utc


async def find(db: AsyncSession, *, user_id: str, operation_id: str) -> Optional[CouponOperation]:
    return await db.scalar(
        select(CouponOperation)
        .where(CouponOperation.user_id == user_id, CouponOperation.operation_id == operation_id)
        .execution_options(populate_existing=True)
    )


async def pending(
    db: AsyncSession, *, user_id: Optional[str] = None, coupon_id: Optional[str] = None
) -> list[CouponOperation]:
    query = select(CouponOperation).where(CouponOperation.status == "pending")
    if user_id is not None:
        query = query.where(CouponOperation.user_id == user_id)
    if coupon_id is not None:
        query = query.where(CouponOperation.coupon_id == coupon_id)
    return list(await db.scalars(query.order_by(CouponOperation.coupon_id, CouponOperation.id)))


async def require_settled(db: AsyncSession, *, user_id: str) -> None:
    if await pending(db, user_id=user_id):
        raise ConflictError(
            "Your coupon redemption is being confirmed. Retry its status before changing billing or deleting your account."
        )


def response(operation: CouponOperation) -> CouponRedemptionResponse:
    offer = CouponPreviewResponse.model_validate(operation.offer)
    return CouponRedemptionResponse(
        operation_id=operation.operation_id,
        status=operation.status,
        months=offer.months,
        starts_at=offer.starts_at,
        ends_at=offer.ends_at,
        next_payment_at=offer.next_payment_at,
        detail=operation.detail,
    )


async def monthly_state(
    db: AsyncSession, *, user_id: str, subscriptions: Sequence[SubscriptionState], now: datetime
) -> Optional[SubscriptionState]:
    running = [s for s in subscriptions if s.status not in {"canceled", "incomplete_expired"}]
    if not running:
        if await service.get_user_subscription(db, user_id=user_id):
            raise ConflictError("Your subscription is being updated. Retry after billing settles.")
        return None
    if len(running) != 1:
        raise ConflictError("Resolve your subscriptions before using a coupon.")
    state = running[0]
    existing = await service.get_free_access(db, user_id=user_id, now=now)
    backed = bool(
        existing
        and state.coupon_operation
        and state.trial_end
        and as_utc(state.trial_end) == as_utc(existing.ends_at)
        and await db.scalar(
            select(CouponOperation.id).where(
                CouponOperation.id == state.coupon_operation,
                CouponOperation.user_id == user_id,
                CouponOperation.status == "completed",
            )
        )
    )
    if (
        state.status not in ({"active", "trialing"} if backed else {"active"})
        or state.cancel_at is not None
        or state.paused
        or state.has_pending_update
        or state.schedule_id
        or state.item_count != 1
        or not state.item_id
        or not state.price_id
        or state.plan_key not in settings.BILLING_PLAN_KEYS
        or state.interval != "month"
        or state.interval_count != 1
        or state.billing_mode not in {"classic", "flexible"}
        or not state.billing_cycle_anchor
        or not state.current_period_start
        or not state.current_period_end
        or not (backed or state.paid_current_period)
        or not as_utc(state.current_period_start) <= now < as_utc(state.current_period_end)
    ):
        raise ConflictError(
            "Coupons currently require a paid-up renewing monthly subscription. Keep your code for annual plans, introductory trials or cancelled renewal, and resolve any unsettled payment first."
        )
    if not backed:
        assert (
            state.billing_cycle_anchor is not None
            and state.current_period_end is not None
            and state.current_period_start is not None
        )
        paid = paid_period(state.billing_cycle_anchor, now)
        if paid.start != as_utc(state.current_period_start) or paid.end != as_utc(
            state.current_period_end
        ):
            raise ConflictError(
                "Your paid period has an unsupported boundary. Contact support before using a coupon."
            )
    return state


async def prepare(
    db: AsyncSession,
    *,
    user: User,
    coupon: Coupon,
    offer: CouponPreviewResponse,
    request: CouponRedemptionRequest,
    state: SubscriptionState,
    now: datetime,
) -> CouponOperation:
    candidates = await coupon_service.require_unclaimed(
        db, coupon=coupon, email=user.email, config=settings
    )
    if (
        coupon.redeemed_count + len(await pending(db, coupon_id=coupon.id))
        >= coupon.max_redemptions
    ):
        raise ConflictError("This coupon is being claimed. Try again later or ask its sender.")
    key_id, _ = settings.coupon_identity_keys()
    claim = CouponClaim(coupon_id=coupon.id, key_id=key_id, fingerprint=candidates[key_id])
    db.add(claim)
    await db.flush()
    subscription = await service.get_user_subscription(db, user_id=user.id)
    if (
        subscription is None
        or subscription.stripe_subscription_id != state.id
        or state.billing_cycle_anchor is None
        or state.current_period_end is None
    ):
        raise ConflictError("Your subscription is being updated. Try again.")
    if state.paid_current_period and (
        subscription.paid_end is None or as_utc(subscription.paid_end) <= now
    ):
        period = paid_period(state.billing_cycle_anchor, now)
        subscription.paid_start = period.start
        subscription.paid_end = state.current_period_end
        subscription.paid_anchor = state.billing_cycle_anchor
        subscription.paid_allowance = asdict(limits(trial=False))
    previous = await service.get_free_access(db, user_id=user.id, now=now)
    anchor = (
        (previous.calendar_anchor or previous.starts_at) if previous else subscription.paid_anchor
    )
    assert anchor is not None
    anchor = as_utc(anchor)
    offset = (
        previous.month_offset + previous.months
        if previous
        else (offer.starts_at.year - anchor.year) * 12 + offer.starts_at.month - anchor.month
    )
    original = {
        "item_id": state.item_id,
        "price_id": state.price_id,
        "billing_mode": state.billing_mode,
        "period_end": state.current_period_end.isoformat(),
        "trial_end": state.trial_end.isoformat() if state.trial_end else None,
        "marker": state.coupon_operation,
        "anchor": anchor.isoformat(),
        "offset": offset,
        "coverage_starts_at": as_utc(previous.coverage_starts_at or previous.starts_at).isoformat()
        if previous
        else offer.starts_at.isoformat(),
    }
    operation = CouponOperation(
        user_id=user.id,
        coupon_id=coupon.id,
        claim_id=claim.id,
        operation_id=request.operation_id,
        revision_digest=hashlib.sha256(request.revision.get_secret_value().encode()).hexdigest(),
        customer_id=user.stripe_customer_id,
        subscription_id=state.id,
        original=original,
        offer={**offer.model_dump(mode="json"), "revision": ""},
        acceptance={
            "terms_version": offer.terms_version,
            "language": request.language,
            "accepted_terms": bool(request.accepted_terms) if offer.terms_version else False,
            "approved_specific_clauses": bool(request.approved_specific_clauses)
            if offer.terms_version
            else False,
            "requested_immediate_start": False,
            "next_payment_at": offer.ends_at.isoformat(),
        },
        target=offer.ends_at,
        created_at=now,
        status="pending",
        attempts=0,
    )
    db.add(operation)
    await db.flush()
    return operation


def compatible(state: SubscriptionState, operation: CouponOperation) -> bool:
    return (
        state.item_count == 1
        and state.interval == "month"
        and state.interval_count == 1
        and state.item_id == operation.original["item_id"]
        and state.price_id == operation.original["price_id"]
        and state.billing_mode == operation.original["billing_mode"]
        and not state.has_pending_update
        and not state.schedule_id
        and not state.paused
    )


async def reconcile(
    db: AsyncSession,
    gateway: BillingGateway,
    *,
    user: User,
    operation: CouponOperation,
    now: datetime,
    mutate: bool = True,
) -> CouponRedemptionResponse:
    coupon = await coupon_redemption.lock_coupon(db, operation.coupon_id)
    refreshed = await find(db, user_id=user.id, operation_id=operation.operation_id)
    assert refreshed is not None
    operation = refreshed
    if operation.status != "pending":
        return response(operation)
    operation.detail = (
        "Confirming redemption. Your place is reserved; retry this operation or contact support."
    )
    try:
        states = await gateway.list_subscriptions(customer_id=operation.customer_id)
        state = next((s for s in states if s.id == operation.subscription_id), None)
        if (
            len([s for s in states if s.status not in {"canceled", "incomplete_expired"}]) > 1
            or state is None
            or user.stripe_customer_id != operation.customer_id
            or not compatible(state, operation)
        ):
            operation.detail = "Billing changed while confirming redemption. Contact support; your redemption remains reserved."
            return response(operation)
        applied = (
            state.coupon_operation == operation.id
            and state.trial_end is not None
            and as_utc(state.trial_end) == as_utc(operation.target)
        )
        if not applied and mutate:
            unchanged = (
                state.status in {"active", "trialing"}
                and state.cancel_at is None
                and state.current_period_end is not None
                and as_utc(state.current_period_end).isoformat() == operation.original["period_end"]
                and (state.trial_end.isoformat() if state.trial_end else None)
                == operation.original["trial_end"]
                and state.coupon_operation == operation.original["marker"]
            )
            if (
                not unchanged
                or as_utc(operation.target) <= now
                or (as_utc(operation.target) - now).total_seconds() > 730 * 86400
            ):
                operation.detail = "Billing changed while confirming redemption. Contact support; no further change was sent."
                return response(operation)
            if await gateway.has_unsettled_invoices(
                customer_id=operation.customer_id
            ) or await gateway.has_pending_checkout(customer_id=operation.customer_id):
                return response(operation)
            operation.attempts += 1
            try:
                await gateway.defer_renewal(
                    subscription_id=operation.subscription_id,
                    target=as_utc(operation.target),
                    operation_id=operation.id,
                )
            except DeferralRefused:
                operation.status = "refused"
                operation.detail = "The billing provider refused this redemption. The coupon was not consumed; contact its sender or check the code again."
                operation.resolved_at = now
                claim = await db.get(CouponClaim, operation.claim_id)
                operation.claim_id = None
                await db.flush()
                if claim:
                    await db.delete(claim)
                return response(operation)
            states = await gateway.list_subscriptions(customer_id=operation.customer_id)
            state = next((s for s in states if s.id == operation.subscription_id), None)
            applied = (
                state is not None
                and compatible(state, operation)
                and state.coupon_operation == operation.id
                and state.trial_end is not None
                and as_utc(state.trial_end) == as_utc(operation.target)
            )
        if not applied:
            return response(operation)
        await service.sync_customer(db, gateway, user_id=user.id, customer_id=operation.customer_id)
        offer = CouponPreviewResponse.model_validate(operation.offer)
        access = FreeAccess(
            user_id=user.id,
            coupon_id=coupon.id,
            claim_id=operation.claim_id,
            operation_id=operation.operation_id,
            revision_digest=operation.revision_digest,
            calendar_anchor=datetime.fromisoformat(operation.original["anchor"]),
            month_offset=operation.original["offset"],
            coverage_starts_at=datetime.fromisoformat(operation.original["coverage_starts_at"]),
            months=offer.months,
            starts_at=offer.starts_at,
            ends_at=offer.ends_at,
            allowance=offer.allowance.model_dump(),
            accepted_at=operation.created_at,
            acceptance={**operation.acceptance, "offer": operation.offer},
        )
        db.add(access)
        if await db.get(CouponHistory, user.id) is None:
            db.add(CouponHistory(user_id=user.id))
        coupon.redeemed_count += 1
        if coupon.redeemed_count == coupon.max_redemptions:
            coupon.unclaimable_at = now
        operation.status = "completed"
        operation.detail = None
        operation.resolved_at = now
        await db.flush()
    except BillingProviderError:
        pass
    return response(operation)


async def recovery_candidates(
    db: AsyncSession, *, operation_id: Optional[str] = None, limit: int = 100
) -> list[tuple[str, str]]:
    query = (
        select(CouponOperation.user_id, CouponOperation.operation_id)
        .where(CouponOperation.status == "pending")
        .order_by(CouponOperation.created_at, CouponOperation.id)
        .limit(limit)
    )
    if operation_id:
        query = query.where(CouponOperation.id == operation_id)
    return [(row[0], row[1]) for row in await db.execute(query)]
