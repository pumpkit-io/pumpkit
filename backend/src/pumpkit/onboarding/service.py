from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.billing import service as billing_service
from pumpkit.onboarding.schemas import NextStep


async def next_step(db: AsyncSession, *, user_id: str) -> Optional[NextStep]:
    """The Paywall comes first and is checked on every visit (ADR 0018)."""
    if not await billing_service.has_access(db, user_id=user_id):
        return "paywall"
    return None
