import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Optional, Sequence

from itsdangerous import URLSafeSerializer
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.billing import coupon_service, service
from pumpkit.billing.allowance import limits, months_after
from pumpkit.billing.gateway import SubscriptionState
from pumpkit.billing.models import Coupon
from pumpkit.billing.schemas import CouponPreviewResponse, OfferedAllowanceResponse
from pumpkit.billing.terms import TERMS_VERSION
from pumpkit.core.config import settings
from pumpkit.core.errors import ConflictError, NotConfiguredError
from pumpkit.core.time import as_utc


async def preview(
    db: AsyncSession,
    *,
    user: User,
    subscriptions: Sequence[SubscriptionState],
    now: datetime,
    code: str = "",
    coupon: Optional[Coupon] = None,
) -> CouponPreviewResponse:
    try:
        coupon_service.require_enabled(settings)
    except coupon_service.CouponCommandError as exc:
        raise NotConfiguredError("Coupons are unavailable on this instance.") from exc
    if coupon is None:
        coupon = await coupon_service.find_by_code(db, code.strip())
    if (
        coupon is None
        or coupon.disabled_at is not None
        or (coupon.claim_deadline is not None and as_utc(coupon.claim_deadline) <= now)
        or coupon.redeemed_count >= coupon.max_redemptions
    ):
        raise ConflictError(
            "This coupon is unavailable. Check the code or ask its sender for another."
        )
    try:
        recipient_matches = coupon_service.matches_recipient(coupon, user.email, config=settings)
    except coupon_service.CouponCommandError as exc:
        raise NotConfiguredError(
            "This coupon cannot be checked right now. Contact support."
        ) from exc
    if not recipient_matches:
        raise ConflictError(
            "This coupon is unavailable for your account. Check the code with its sender."
        )
    if set(coupon.plan_keys) != set(settings.BILLING_PLAN_KEYS):
        raise ConflictError("This coupon's offer is unavailable. Contact its sender.")
    if any(state.has_pending_update or state.schedule_id for state in subscriptions):
        raise ConflictError(
            "Your subscription has a pending change. Resolve it before using a coupon."
        )
    if any(
        state.status in {"incomplete", "past_due", "unpaid", "paused"}
        or state.latest_invoice_status not in {None, "paid", "void"}
        for state in subscriptions
    ):
        raise ConflictError(
            "Resolve your outstanding or processing payment in the billing portal before using a coupon."
        )
    if any(
        state.status not in {"canceled", "incomplete_expired"} for state in subscriptions
    ) or await service.get_user_subscription(db, user_id=user.id):
        raise ConflictError(
            "Coupons for an existing subscription are not available yet. Keep your code and try again later."
        )
    await coupon_service.require_unclaimed(db, coupon=coupon, email=user.email, config=settings)
    if await service.get_free_access(db, user_id=user.id, now=now):
        raise ConflictError("Adding another coupon is not available yet. Keep your code for later.")
    if coupon.months > 24:
        raise ConflictError(
            "This coupon would exceed the supported 730-day access horizon. Ask its sender for a shorter benefit."
        )
    end = months_after(now, coupon.months)
    if (end - now).total_seconds() > 730 * 86400:
        raise ConflictError(
            "This coupon would exceed the supported 730-day access horizon. Ask its sender for a shorter benefit."
        )
    allowance = OfferedAllowanceResponse(**asdict(limits(trial=False)))
    response = CouponPreviewResponse(
        months=coupon.months,
        starts_at=now,
        ends_at=end,
        allowance=allowance,
        next_payment_at=None,
        terms_version=TERMS_VERSION if service.requires_terms_acceptance() else None,
        revision="",
    )
    offer = response.model_dump(mode="json", exclude={"revision"})
    state = {
        "code_digest": coupon.code_digest,
        "plan_keys": coupon.plan_keys,
        "claim_deadline": as_utc(coupon.claim_deadline).isoformat()
        if coupon.claim_deadline
        else None,
        "recipient_key_id": coupon.recipient_key_id,
        "recipient_fingerprint": coupon.recipient_fingerprint,
    }
    state_digest = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
    revision = URLSafeSerializer(settings.JWT_SECRET_KEY, salt="coupon-preview").dumps(
        {
            "offer": offer,
            "user_id": user.id,
            "coupon_id": coupon.id,
            "state": state_digest,
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=10)).isoformat(),
        }
    )
    return response.model_copy(update={"revision": revision})
