from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.authors import service as authors_service
from pumpkit.billing import service as billing_service
from pumpkit.core.errors import ConflictError
from pumpkit.onboarding.models import OnboardingFinish
from pumpkit.onboarding.schemas import NextStep


async def next_step(db: AsyncSession, *, user_id: str) -> Optional[NextStep]:
    """The Paywall comes first and is checked on every visit, even after Onboarding (ADR 0018)."""
    if not await billing_service.has_access(db, user_id=user_id):
        return "paywall"
    if await db.get(OnboardingFinish, user_id) is not None:
        return None
    return "persona"


async def finish(db: AsyncSession, *, user_id: str, now: datetime) -> None:
    """Record that the User finished Onboarding, keeping the first time. Flushes."""
    if await db.get(OnboardingFinish, user_id) is not None:
        return
    authors = await authors_service.list_authors(db, user_id=user_id)
    if not any(author.post_count > 0 for author in authors):
        raise ConflictError("Pick at least one inspiration author to continue.")
    db.add(OnboardingFinish(user_id=user_id, finished_at=now))
    await db.flush()
