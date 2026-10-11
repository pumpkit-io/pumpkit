"""The subscribed-User dependency that routers of every area above billing gate on."""

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.dependencies import get_current_user
from pumpkit.auth.models import User
from pumpkit.billing import service
from pumpkit.core.db.session import get_async_db


async def require_subscribed_user(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_async_db)
) -> User:
    """
    The signed-in User, if Subscribed; else a 403. Reads only Pumpkit's copy of the
    Subscription (ADR 0004), so a payment Stripe hasn't synced yet doesn't count.
    """
    subscription = await service.get_user_subscription(db, user_id=current_user.id)
    if not service.is_subscribed(subscription):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This needs a Subscription. Subscribe to continue.",
        )
    return current_user
