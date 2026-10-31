from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.dependencies import get_current_user
from pumpkit.auth.models import User
from pumpkit.core.db.session import get_async_db
from pumpkit.onboarding import service
from pumpkit.onboarding.schemas import OnboardingResponse

router = APIRouter(tags=["onboarding"])


# Open to Users who aren't Subscribed: it is how the web app knows to show them the Paywall.
@router.get("/onboarding", response_model=OnboardingResponse, status_code=status.HTTP_200_OK)
async def get_onboarding(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> OnboardingResponse:
    return OnboardingResponse(next_step=await service.next_step(db, user_id=current_user.id))
