from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.dependencies import get_current_user
from pumpkit.auth.models import User
from pumpkit.billing.dependencies import require_subscribed_user
from pumpkit.core.db.session import get_async_db
from pumpkit.core.time import Clock, get_clock
from pumpkit.onboarding import mediator
from pumpkit.onboarding.schemas import OnboardingResponse

router = APIRouter(tags=["onboarding"])


# Open to Users who aren't Subscribed: it is how the web app knows to show them the Paywall.
@router.get("/onboarding", response_model=OnboardingResponse, status_code=status.HTTP_200_OK)
async def get_onboarding(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> OnboardingResponse:
    return await mediator.get_onboarding(db, current_user)


@router.post("/onboarding/finish", status_code=status.HTTP_204_NO_CONTENT)
async def finish_onboarding(
    current_user: User = Depends(require_subscribed_user),
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> None:
    await mediator.finish(db, current_user, clock())
