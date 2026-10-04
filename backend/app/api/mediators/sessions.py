from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.refresh_tokens as refresh_tokens_service
import app.api.services.users as user_service
from app.core.config import settings
from app.core.logger import logger
from app.core.security import (
    create_access_token,
    create_auth_response,
    create_refresh_token,
    hash_token,
    verify_refresh_token,
)


async def refresh_token(request: Request, db: AsyncSession) -> JSONResponse:
    """
    Refresh an access token using the refresh token contained in the given request's cookies.
    """
    # Get refresh token from cookie
    cookie_name = "__Host-refresh_token" if settings.is_env_production() else "refresh_token"
    refresh_token_value = request.cookies.get(cookie_name)

    if not refresh_token_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify JWT structure and claims first
    payload = verify_refresh_token(token=refresh_token_value)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate against database and lock the row so a concurrent request
    # cannot rotate the same token at the same time.
    refresh_token_hash = hash_token(refresh_token_value)
    db_refresh_token = await refresh_tokens_service.get_active_refresh_token_by_hash(
        db=db, token_hash=refresh_token_hash, lock_for_update=True
    )

    if not db_refresh_token or db_refresh_token.user_id != user_id:
        # A malicious attacker is probably replaying a stolen refresh token.
        # Check if the token exists in the database and is revoked - if so,
        # the same token was already used in another request.
        stale_token = await refresh_tokens_service.get_refresh_token_by_hash(
            db=db,
            token_hash=refresh_token_hash,
        )
        if stale_token and stale_token.is_revoked:
            # Token reuse detected - revoke the whole Session to protect the User
            logger.error(
                "Refresh token reuse detected: revoking Session (session_id=%s, user_id=%s)",
                stale_token.session_id,
                stale_token.user_id,
            )
            await refresh_tokens_service.revoke_session(db=db, session_id=stale_token.session_id)

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get user to include them in the new access token
    user = await user_service.get_user_by_id(db=db, user_id=user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create new access token (rotating the refresh token below revokes the old one)
    new_access_token = create_access_token(
        data={
            "sub": user.id,
            "email": user.email,
        },
    )

    # Create new refresh token (token rotation)
    new_refresh_token = create_refresh_token(
        data={
            "sub": user.id,
            "email": user.email,
        },
    )
    await refresh_tokens_service.create_refresh_token(
        db=db,
        user_id=user.id,
        refresh_token=new_refresh_token,
        sign_in_method=db_refresh_token.sign_in_method,
        session_id=db_refresh_token.session_id,
        previous_token=db_refresh_token,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    refresh_response: JSONResponse = create_auth_response(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
    )

    return refresh_response


async def logout(request: Request, db: AsyncSession) -> JSONResponse:
    """
    Logout user by revoking their refresh token.
    """
    cookie_name = "__Host-refresh_token" if settings.is_env_production() else "refresh_token"
    refresh_token_value = request.cookies.get(cookie_name)

    # A missing or invalid refresh token means there is no Session to revoke:
    # the User is already signed out, so that still succeeds. Anything that
    # fails while revoking is unexpected and reaches the global handler.
    if refresh_token_value:
        payload = verify_refresh_token(token=refresh_token_value)
        user_id = payload.get("sub") if payload else None
        if user_id:
            await refresh_tokens_service.revoke_all_user_sessions(db=db, user_id=user_id)

    response = JSONResponse(
        content={"message": "Logged out successfully"}, status_code=status.HTTP_200_OK
    )
    response.delete_cookie(
        key=cookie_name,
        path="/",
        httponly=True,
        secure=settings.is_env_production(),
        samesite="lax",
    )
    return response
