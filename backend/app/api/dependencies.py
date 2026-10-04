"""FastAPI request dependencies shared by routers."""

from typing import Optional

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.sessions as sessions
import app.api.services.users as user_service
from app.core.security import get_bearer_token, verify_access_token
from app.db.models import User
from app.db.session import get_async_db


async def get_current_user(
    token: str = Depends(get_bearer_token), db: AsyncSession = Depends(get_async_db)
) -> User:
    """
    Resolve the User from the request's bearer token, or raise a 401 challenge.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Verify and decode the JWT token
    payload = verify_access_token(token)
    if payload is None:
        raise credentials_exception

    # Extract user ID from token payload
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
