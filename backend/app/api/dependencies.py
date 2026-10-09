"""FastAPI request dependencies shared by routers."""

from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.sessions as sessions
import app.api.services.subscriptions as subscriptions_service
import app.api.services.users as user_service
from app.core.security import get_bearer_token, verify_access_token
from app.db.models import User
from app.db.session import get_async_db


async def get_current_user(
    token: str = Depends(get_bearer_token), db: AsyncSession = Depends(get_async_db)
) -> User:
    """Resolve the User from the request's bearer token, or raise a 401 challenge."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = verify_access_token(token)
    if payload is None:
        raise credentials_exception

    user_id: Optional[str] = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    user = await user_service.get_user_by_id(db=db, user_id=user_id)
    if user is None:
        raise credentials_exception

    # A Suspended User's access tokens stop working on their next request.
    if not sessions.may_hold_session(user):
        raise credentials_exception

    return user


async def require_subscribed_user(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_async_db)
) -> User:
    """
    The signed-in User, if Subscribed or SUBSCRIPTION_REQUIRED is off; else a 403.
    Reads only Pumpkit's copy of the Subscription (ADR 0004), so a payment Stripe
    hasn't synced yet doesn't count.
    """
    subscription = await subscriptions_service.get_user_subscription(db, user_id=current_user.id)
    if not subscriptions_service.grants_access(subscription):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This needs a Subscription. Subscribe to continue.",
        )
    return current_user
