import hashlib
import hmac

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.service import users
from pumpkit.billing.models import TrialEligibility
from pumpkit.core.config import settings
from pumpkit.core.errors import AppError


class TrialEligibilityUnavailableError(AppError):
    status_code = 503
    reported = True
    public_detail = "Trial eligibility is unavailable. Please contact support."


def fingerprints(x_user_id: str) -> tuple[str, dict[str, str]]:
    try:
        active, keys = settings.trial_identity_keys()
    except ValueError:
        raise TrialEligibilityUnavailableError("TRIAL_IDENTITY_KEYS is unavailable") from None
    message = "\0".join(("pumpkit-trial-eligibility", "x-account", x_user_id)).encode()
    return active, {
        key_id: hmac.new(key, message, hashlib.sha256).hexdigest() for key_id, key in keys.items()
    }


async def _matching_records(db: AsyncSession, fingerprints: dict[str, str]):
    return list(
        (
            await db.scalars(
                select(TrialEligibility).where(
                    tuple_(TrialEligibility.key_id, TrialEligibility.fingerprint).in_(
                        list(fingerprints.items())
                    )
                )
            )
        ).all()
    )


async def may_start_trial(db: AsyncSession, *, user_id: str) -> bool:
    user = await users.get_user_by_id(db, user_id)
    if user is None or user.x_user_id is None:
        return True
    _, candidates = fingerprints(user.x_user_id)
    records = await _matching_records(db, candidates)
    if any(not record.eligible for record in records):
        return False
    retained_keys = set(await db.scalars(select(TrialEligibility.key_id).distinct()))
    if retained_keys - candidates.keys():
        # An unavailable historical key could hide this account's earlier eligibility record.
        raise TrialEligibilityUnavailableError("Restore historical TRIAL_IDENTITY_KEYS")
    return True


async def exclude(db: AsyncSession, *, user_id: str) -> None:
    user = await users.lock_user_id(db, user_id=user_id)
    if user is None or user.x_user_id is None:
        return
    active, candidates = fingerprints(user.x_user_id)
    record = await db.get(TrialEligibility, (active, candidates[active]))
    if record is None:
        db.add(TrialEligibility(key_id=active, fingerprint=candidates[active], eligible=False))
    else:
        record.eligible = False
    await db.flush()
