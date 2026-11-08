import hashlib
import hmac
import secrets
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.billing.coupon_identity import fingerprints
from pumpkit.billing.gateway import Plan
from pumpkit.billing.models import Coupon, CouponClaim, FreeAccess
from pumpkit.billing.schemas import CouponIssueRequest
from pumpkit.core.config import Settings
from pumpkit.core.errors import ConflictError, NotConfiguredError
from pumpkit.core.ids import ulid_with_prefix
from pumpkit.core.logging import logger
from pumpkit.core.time import as_utc


class CouponCommandError(Exception):
    pass


def coupons_available(config: Settings) -> bool:
    return config.COUPONS_ENABLED and config.is_stripe_billing_configured()


def require_enabled(config: Settings) -> None:
    if not coupons_available(config):
        raise CouponCommandError(
            "Coupons require enabled coupon functionality and configured plans."
        )


def validate_offers(plans: Sequence[Plan], *, config: Settings) -> None:
    if (
        {plan.key for plan in plans} != set(config.BILLING_PLAN_KEYS)
        or not plans
        or any(plan.interval not in {"month", "year"} or plan.interval_count != 1 for plan in plans)
        or len({(plan.product_name, plan.currency) for plan in plans}) != 1
    ):
        raise CouponCommandError(
            "Coupons require compatible monthly or annual plans for the same offer and currency."
        )


async def issue(
    db: AsyncSession, *, request: CouponIssueRequest, config: Settings, now: datetime
) -> tuple[Coupon, str]:
    require_enabled(config)
    if request.claim_deadline is not None and request.claim_deadline <= now:
        raise CouponCommandError("The claim deadline must be in the future.")
    code = secrets.token_urlsafe(32)
    coupon_id = ulid_with_prefix("coupon")
    key_id = fingerprint = None
    if request.recipient is not None:
        key_id, _ = config.coupon_identity_keys()
        fingerprint = fingerprints(
            config=config, coupon_id=coupon_id, email=str(request.recipient), purpose="recipient"
        )[key_id]
    coupon = Coupon(
        id=coupon_id,
        recipient_restricted=request.recipient is not None,
        recipient_key_id=key_id,
        recipient_fingerprint=fingerprint,
        code_digest=hashlib.sha256(code.encode()).hexdigest(),
        months=request.months,
        max_redemptions=request.max_redemptions,
        claim_deadline=request.claim_deadline,
        plan_keys=list(config.BILLING_PLAN_KEYS),
        created_at=now,
    )
    db.add(coupon)
    await db.flush()
    return coupon, code


async def find_by_code(db: AsyncSession, code: str) -> Optional[Coupon]:
    return await db.scalar(
        select(Coupon).where(Coupon.code_digest == hashlib.sha256(code.encode()).hexdigest())
    )


async def inspect(db: AsyncSession, coupon_id: str) -> Coupon:
    coupon = await db.get(Coupon, coupon_id)
    if coupon is None:
        raise CouponCommandError("Coupon not found.")
    return coupon


def describe(coupon: Coupon) -> dict[str, object]:
    return {
        "id": coupon.id,
        "months": coupon.months,
        "max_redemptions": coupon.max_redemptions,
        "recipient_restricted": coupon.recipient_restricted,
        "recipient_retained": coupon.recipient_fingerprint is not None,
        "created_at": as_utc(coupon.created_at).isoformat(),
        "claim_deadline": as_utc(coupon.claim_deadline).isoformat()
        if coupon.claim_deadline
        else None,
        "disabled_at": as_utc(coupon.disabled_at).isoformat() if coupon.disabled_at else None,
        "unclaimable_at": as_utc(coupon.unclaimable_at).isoformat()
        if coupon.unclaimable_at
        else None,
        "redeemed_count": coupon.redeemed_count,
        "benefit_kind": coupon.benefit_kind,
        "plan_keys": coupon.plan_keys,
    }


def matches_recipient(coupon: Coupon, email: str, *, config: Settings) -> bool:
    if not coupon.recipient_restricted:
        return True
    candidates = fingerprints(config=config, coupon_id=coupon.id, email=email, purpose="recipient")
    if coupon.recipient_key_id is None or coupon.recipient_fingerprint is None:
        return False
    if coupon.recipient_key_id not in candidates:
        logger.error("Coupon identity key missing for coupon %s", coupon.id)
        raise CouponCommandError(
            "A required coupon identity key is unavailable. Restore the complete key ring."
        )
    return hmac.compare_digest(coupon.recipient_fingerprint, candidates[coupon.recipient_key_id])


async def list_coupons(db: AsyncSession) -> list[Coupon]:
    return list(await db.scalars(select(Coupon).order_by(Coupon.created_at.desc(), Coupon.id)))


async def disable(db: AsyncSession, coupon_id: str, *, now: datetime) -> Coupon:
    coupon = await db.scalar(
        select(Coupon)
        .where(Coupon.id == coupon_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if coupon is None:
        raise CouponCommandError("Coupon not found.")
    if coupon.disabled_at is None:
        terminal = now
        if coupon.unclaimable_at is not None:
            terminal = min(terminal, as_utc(coupon.unclaimable_at))
        if coupon.claim_deadline is not None:
            terminal = min(terminal, as_utc(coupon.claim_deadline))
        coupon.disabled_at = now
        coupon.unclaimable_at = terminal
        await db.flush()
    return coupon


async def purge(db: AsyncSession, *, now: datetime) -> int:
    candidates = await db.scalars(
        select(Coupon)
        .where(
            or_(Coupon.unclaimable_at <= now, Coupon.claim_deadline <= now),
        )
        .order_by(Coupon.id)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    purged = 0
    for coupon in candidates:
        if coupon.unclaimable_at is None and coupon.claim_deadline is not None:
            coupon.unclaimable_at = as_utc(coupon.claim_deadline)
        if (
            coupon.recipient_fingerprint is not None
            and coupon.unclaimable_at is not None
            and as_utc(coupon.unclaimable_at) + timedelta(days=30) <= now
        ):
            coupon.recipient_key_id = None
            coupon.recipient_fingerprint = None
            purged += 1
        if (
            coupon.unclaimable_at is not None
            and as_utc(coupon.unclaimable_at) + timedelta(days=30) <= now
        ):
            removed = await db.scalars(
                delete(CouponClaim)
                .where(CouponClaim.coupon_id == coupon.id)
                .returning(CouponClaim.id)
            )
            purged += len(list(removed))
    ended = await db.scalars(
        delete(FreeAccess)
        .where(FreeAccess.ends_at <= now - timedelta(days=90))
        .returning(FreeAccess.id)
    )
    purged += len(list(ended))
    await db.flush()
    return purged


async def require_unclaimed(
    db: AsyncSession, *, coupon: Coupon, email: str, config: Settings
) -> dict[str, str]:
    from_config = fingerprints(config=config, coupon_id=coupon.id, email=email, purpose="claim")
    retained = list(await db.scalars(select(CouponClaim).where(CouponClaim.coupon_id == coupon.id)))
    if any(claim.key_id not in from_config for claim in retained):
        logger.error("Coupon claim key missing for coupon %s", coupon.id)
        raise NotConfiguredError("A coupon identity key is unavailable. Contact support.")
    if any(hmac.compare_digest(claim.fingerprint, from_config[claim.key_id]) for claim in retained):
        raise ConflictError("You have already redeemed this coupon.")
    return from_config
