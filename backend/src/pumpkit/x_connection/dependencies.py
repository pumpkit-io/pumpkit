from fastapi import Depends

from pumpkit.auth.dependencies import get_current_user
from pumpkit.auth.models import User
from pumpkit.core.errors import ConflictError


async def require_x_connection_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.x_user_id is not None:
        return current_user
    raise ConflictError(
        "Sign out and continue with X to use your X account.", code="X_IDENTITY_REQUIRED"
    )
