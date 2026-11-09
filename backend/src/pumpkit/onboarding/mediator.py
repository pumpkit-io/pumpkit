from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.onboarding import service
from pumpkit.onboarding.schemas import OnboardingResponse


async def get_onboarding(
    db: AsyncSession, user: User, now: Optional[datetime] = None
) -> OnboardingResponse:
    return OnboardingResponse(next_step=await service.next_step(db, user_id=user.id, now=now))


async def finish(db: AsyncSession, user: User, now: datetime) -> None:
    await service.finish(db, user_id=user.id, now=now)
    await db.commit()
