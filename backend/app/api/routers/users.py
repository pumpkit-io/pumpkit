from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.users as user_service
from app.api.dependencies import get_current_user
from app.db.models import User
from app.db.session import get_async_db
from app.schemas.users import UserProfileResponse, UserProfileUpdate

router = APIRouter(tags=["users"])


@router.get("/users/me", response_model=UserProfileResponse, status_code=status.HTTP_200_OK)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
) -> UserProfileResponse:
    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        avatar_data_url=current_user.avatar_data_url,
    )


@router.patch("/users/me", response_model=UserProfileResponse, status_code=status.HTTP_200_OK)
async def update_current_user_profile(
    update: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> UserProfileResponse:
    """Apply only the fields present in the body; ``null`` clears a field (e.g. the avatar)."""

    current_user = await user_service.update_user_profile(
        db=db, user=current_user, changes=update.model_dump(exclude_unset=True)
    )

    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        avatar_data_url=current_user.avatar_data_url,
    )
