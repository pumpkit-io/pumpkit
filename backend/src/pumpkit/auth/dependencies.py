"""Bearer parsing and the current-User dependency every signed-in route depends on."""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.auth.service.sessions as sessions
import pumpkit.auth.service.users as user_service
from pumpkit.auth.models import User
from pumpkit.auth.tokens import verify_access_token
from pumpkit.core.db.session import get_async_db

# Plain bearer scheme: access tokens come from magic-link and OAuth sign-in, not a password grant.
# auto_error=False so we raise the 401 and Bearer challenge ourselves, whatever FastAPI's default.
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_bearer_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> str:
    """FastAPI dependency: the raw bearer token, or 401 if it is missing or malformed."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


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
