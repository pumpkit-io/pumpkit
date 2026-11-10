import hmac
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.billing import coupon_identity, coupon_redemption, trial_eligibility
from pumpkit.billing.models import CouponClaim, CouponOperation, FreeAccess, TrialEligibility
from pumpkit.core.config import settings
from pumpkit.core.errors import ConflictError


@dataclass(frozen=True)
class BenefitReset:
    claims: tuple[CouponClaim, ...]
    trials: tuple[TrialEligibility, ...]


async def prepare(db: AsyncSession, *, user: User) -> BenefitReset:
    _, trial_keys = settings.trial_identity_keys()
    _, trial_candidates = (
        trial_eligibility.fingerprints(user.x_user_id) if user.x_user_id is not None else ("", {})
    )
    retained_trial_keys = set(await db.scalars(select(TrialEligibility.key_id).distinct()))
    if retained_trial_keys - trial_keys.keys():
        raise ConflictError("Restore every historical trial identity key before a prelaunch reset.")
    trials = tuple(
        record
        for record in await db.scalars(select(TrialEligibility))
        if user.x_user_id is not None
        and record.key_id in trial_candidates
        and hmac.compare_digest(record.fingerprint, trial_candidates[record.key_id])
    )
    retained = list(await db.scalars(select(CouponClaim)))
    if not retained:
        return BenefitReset((), trials)
    try:
        _, coupon_keys = settings.coupon_identity_keys()
    except ValueError:
        raise ConflictError("Restore coupon identity keys before a prelaunch reset.") from None
    if {claim.key_id for claim in retained} - coupon_keys.keys():
        raise ConflictError(
            "Restore every historical coupon identity key before a prelaunch reset."
        )
    linked = set(
        await db.scalars(select(FreeAccess.claim_id).where(FreeAccess.user_id == user.id))
    ) | set(
        await db.scalars(select(CouponOperation.claim_id).where(CouponOperation.user_id == user.id))
    )
    shared_email = await db.scalar(
        select(User.id).where(
            User.id != user.id, func.lower(User.email) == user.email.strip().lower()
        )
    )
    claims = []
    for claim in retained:
        email = coupon_identity.fingerprints(
            config=settings, coupon_id=claim.coupon_id, email=user.email, purpose="claim"
        )
        x = (
            coupon_identity.x_fingerprints(
                config=settings, coupon_id=claim.coupon_id, x_user_id=user.x_user_id
            )
            if user.x_user_id is not None
            else {}
        )
        same_x = (
            claim.x_fingerprint is not None
            and claim.key_id in x
            and hmac.compare_digest(claim.x_fingerprint, x[claim.key_id])
        )
        same_email = hmac.compare_digest(claim.fingerprint, email[claim.key_id])
        if not (same_x or same_email or claim.id in linked):
            continue
        if claim.x_fingerprint is not None and not same_x:
            if claim.id in linked:
                raise ConflictError("A selected coupon claim belongs to another X account.")
            continue
        if (
            not same_x
            and claim.id not in linked
            and (user.x_user_id is not None or shared_email is not None)
        ):
            raise ConflictError("A coupon claim cannot be attributed to only the selected account.")
        claims.append(claim)
    coupon_ids = set(
        await db.scalars(select(FreeAccess.coupon_id).where(FreeAccess.user_id == user.id))
    ) | {claim.coupon_id for claim in claims}
    for coupon_id in sorted(coupon_ids):
        await coupon_redemption.lock_coupon(db, coupon_id)
    for claim in claims:
        for model in (FreeAccess, CouponOperation):
            if await db.scalar(
                select(model.id).where(model.claim_id == claim.id, model.user_id != user.id)
            ):
                raise ConflictError("A selected coupon claim is referenced by another account.")
    return BenefitReset(tuple(claims), trials)


async def apply(db: AsyncSession, reset: BenefitReset) -> None:
    for record in (*reset.claims, *reset.trials):
        await db.delete(record)
    await db.flush()
