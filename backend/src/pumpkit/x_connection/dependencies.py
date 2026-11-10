from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.dependencies import get_current_user
from pumpkit.auth.models import User
from pumpkit.billing.dependencies import require_subscribed_user
from pumpkit.core.db.session import get_async_db
from pumpkit.core.time import Clock, get_clock


async def require_x_connection_user(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> User:
    if current_user.x_user_id is not None:
        return current_user
    return await require_subscribed_user(current_user=current_user, db=db, clock=clock)
