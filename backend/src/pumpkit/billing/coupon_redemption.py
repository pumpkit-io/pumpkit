import hashlib
from datetime import datetime
from typing import Optional

from itsdangerous import BadData, URLSafeSerializer
from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.billing import coupon_service, service
from pumpkit.billing.models import Coupon, CouponClaim, CouponHistory, FreeAccess
from pumpkit.billing.schemas import (
    CouponPreviewResponse,
    CouponRedemptionRequest,
    CouponRedemptionResponse,
)
from pumpkit.core.config import settings
from pumpkit.core.errors import ConflictError, NotFoundError, RefusedError
from pumpkit.core.time import as_utc


class SignedPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offer: CouponPreviewResponse
    user_id: str
    coupon_id: str
    state: str
    issued_at: AwareDatetime
    expires_at: AwareDatetime


def decode(revision: str, *, user_id: str, now: datetime) -> SignedPreview:
    try:
        raw = URLSafeSerializer(settings.JWT_SECRET_KEY, salt="coupon-preview").loads(revision)
        raw["offer"]["revision"] = ""
        signed = SignedPreview.model_validate(raw)
        if signed.user_id != user_id or not signed.issued_at <= now < signed.expires_at:
            raise ValueError
        if (signed.expires_at - signed.issued_at).total_seconds() != 600:
            raise ValueError
        return signed
    except (BadData, ValidationError, ValueError, TypeError, KeyError) as exc:
        raise ConflictError(
            "This coupon preview has expired or changed. Check the code again."
        ) from exc


async def lock_coupon(db: AsyncSession, coupon_id: str) -> Coupon:
    coupon = await db.scalar(
        select(Coupon)
        .where(Coupon.id == coupon_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if coupon is None:
        raise ConflictError("This coupon is unavailable. Check the code again.")
    return coupon


async def find_result(db: AsyncSession, *, user_id: str, operation_id: str) -> Optional[FreeAccess]:
    return await db.scalar(
        select(FreeAccess).where(
            FreeAccess.user_id == user_id, FreeAccess.operation_id == operation_id
        )
    )


def result(access: FreeAccess) -> CouponRedemptionResponse:
    return CouponRedemptionResponse(
        operation_id=access.operation_id,
        months=access.months,
        starts_at=as_utc(access.starts_at),
        ends_at=as_utc(access.ends_at),
        next_payment_at=access.acceptance.get("next_payment_at"),
    )


async def lookup(db: AsyncSession, *, user_id: str, operation_id: str) -> CouponRedemptionResponse:
    access = await find_result(db, user_id=user_id, operation_id=operation_id)
    if access is None:
        raise NotFoundError("No completed redemption was found for this operation.")
    return result(access)


def require_same_offer(
    signed: SignedPreview, current: CouponPreviewResponse, request: CouponRedemptionRequest
) -> None:
    before = signed.offer.model_dump(exclude={"revision", "starts_at", "ends_at"})
    after = current.model_dump(exclude={"revision", "starts_at", "ends_at"})
    if (
        before != after
        or signed.offer.starts_at.date() != current.starts_at.date()
        or signed.offer.ends_at.date() != current.ends_at.date()
    ):
        raise ConflictError("The coupon offer has changed. Check the code and review it again.")
    if request.terms_version != current.terms_version:
        raise ConflictError("The Terms have changed. Check the code and review them again.")
    if current.terms_version is not None and not (
        request.accepted_terms and request.approved_specific_clauses
    ):
        raise RefusedError(
            "Accept the Terms and approve the specified clauses to redeem this coupon."
        )


async def grant(
    db: AsyncSession,
    *,
    user: User,
    coupon: Coupon,
    offer: CouponPreviewResponse,
    request: CouponRedemptionRequest,
    now: datetime,
) -> FreeAccess:
    candidates = await coupon_service.require_unclaimed(
        db, coupon=coupon, email=user.email, config=settings
    )
    key_id, _ = settings.coupon_identity_keys()
    claim = CouponClaim(coupon_id=coupon.id, key_id=key_id, fingerprint=candidates[key_id])
    db.add(claim)
    await db.flush()
    previous = await service.get_free_access(db, user_id=user.id, now=now)
    access = FreeAccess(
        coverage_starts_at=(previous.coverage_starts_at or previous.starts_at)
        if previous
        else offer.starts_at,
        calendar_anchor=(previous.calendar_anchor or previous.starts_at)
        if previous
        else offer.starts_at,
        month_offset=previous.month_offset + previous.months if previous else 0,
        user_id=user.id,
        coupon_id=coupon.id,
        claim_id=claim.id,
        operation_id=request.operation_id,
        revision_digest=hashlib.sha256(request.revision.get_secret_value().encode()).hexdigest(),
        months=offer.months,
        starts_at=offer.starts_at,
        ends_at=offer.ends_at,
        allowance=offer.allowance.model_dump(),
        accepted_at=now,
        acceptance={
            "terms_version": offer.terms_version,
            "language": request.language,
            "accepted_terms": bool(request.accepted_terms) if offer.terms_version else False,
            "approved_specific_clauses": bool(request.approved_specific_clauses)
            if offer.terms_version
            else False,
            "requested_immediate_start": False,
            "next_payment_at": None,
            "offer": offer.model_dump(mode="json", exclude={"revision"}),
        },
    )
    db.add(access)
    if await db.get(CouponHistory, user.id) is None:
        db.add(CouponHistory(user_id=user.id))
    coupon.redeemed_count += 1
    if coupon.redeemed_count == coupon.max_redemptions:
        coupon.unclaimable_at = now
    await db.flush()
    return access
