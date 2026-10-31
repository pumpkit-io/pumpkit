from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.authors import service as authors_service
from pumpkit.billing import service as billing_service
from pumpkit.core.config import settings
from pumpkit.core.errors import ConflictError
from pumpkit.onboarding.models import OnboardingFinish
from pumpkit.onboarding.schemas import NextStep
from pumpkit.x_connection import service as x_connection_service


async def _needs_x_connection(db: AsyncSession, *, user_id: str) -> bool:
    """An Instance without X leaves the step out, since no User could ever pass it."""
    if not settings.is_x_configured():
        return False
    return await x_connection_service.get_connection(db, user_id=user_id) is None


async def next_step(db: AsyncSession, *, user_id: str) -> Optional[NextStep]:
    """The Paywall comes first and is checked on every visit, even after Onboarding (ADR 0018)."""
    if not await billing_service.has_access(db, user_id=user_id):
        return "paywall"
    if await db.get(OnboardingFinish, user_id) is not None:
        return None
    if await _needs_x_connection(db, user_id=user_id):
        return "x_connection"
    return "persona"


async def finish(db: AsyncSession, *, user_id: str, now: datetime) -> None:
    """Record that the User finished Onboarding, keeping the first time. Flushes."""
    if await db.get(OnboardingFinish, user_id) is not None:
        return
    if await _needs_x_connection(db, user_id=user_id):
        raise ConflictError("Connect your X account to continue.")
    authors = await authors_service.list_authors(db, user_id=user_id)
    if not any(author.post_count > 0 for author in authors):
        raise ConflictError("Pick at least one inspiration author to continue.")
    db.add(OnboardingFinish(user_id=user_id, finished_at=now))
    await db.flush()
