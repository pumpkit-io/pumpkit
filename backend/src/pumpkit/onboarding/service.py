from datetime import datetime
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.billing import service as billing_service
from pumpkit.core.errors import ConflictError
from pumpkit.onboarding.models import OnboardingFinish
from pumpkit.onboarding.schemas import NextStep
from pumpkit.positioning import service as positioning_service


async def next_step(
    db: AsyncSession, *, user_id: str, now: Optional[datetime] = None
) -> Optional[NextStep]:
    """The Paywall comes first and is checked on every visit, even after Onboarding (ADR 0018)."""
    if not await billing_service.has_access(db, user_id=user_id, now=now):
        return "paywall"
    if await db.get(OnboardingFinish, user_id) is not None:
        return None
    # The Persona step is done once what it asks for exists (ADR 0018, ADR 0024).
    if await positioning_service.get_positioning(db, user_id=user_id) is not None:
        return None
    return "persona"


async def finish(db: AsyncSession, *, user_id: str, now: datetime) -> None:
    """Record that the User finished Onboarding, keeping the first time. Flushes."""
    if await db.get(OnboardingFinish, user_id) is not None:
        return
    if await positioning_service.get_positioning(db, user_id=user_id) is None:
        raise ConflictError("Write your positioning to continue.")
    try:
        async with db.begin_nested():
            db.add(OnboardingFinish(user_id=user_id, finished_at=now))
    except IntegrityError:
        # A concurrent finish passed the check above too and inserted first.
        pass
