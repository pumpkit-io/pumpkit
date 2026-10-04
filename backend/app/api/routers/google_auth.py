from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.google_auth as google_auth_mediator
from app.core.google_sign_in import GoogleSignIn, get_google_sign_in
from app.db.session import get_async_db

router = APIRouter(tags=["auth"])


@router.get("/login/google", status_code=status.HTTP_200_OK)
async def login_google() -> JSONResponse:
    return await google_auth_mediator.login_google()


@router.get("/oauth/google/callback", status_code=status.HTTP_303_SEE_OTHER)
async def oauth_google_callback(
    request: Request,
    # Optional: Google sends `error` without a code when the User cancels, and
    # the browser must still land on the sign-in page, not a validation error.
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_async_db),
    google_sign_in: GoogleSignIn = Depends(get_google_sign_in),
) -> RedirectResponse:
    return await google_auth_mediator.oauth_google_callback(
        request=request,
        db=db,
        google_sign_in=google_sign_in,
        code=code,
        state=state,
        error=error,
    )
