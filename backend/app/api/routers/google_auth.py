from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.google_auth as google_auth_mediator
from app.db.session import get_async_db

router = APIRouter(tags=["auth"])


@router.get("/login/google", status_code=status.HTTP_200_OK)
async def login_google() -> JSONResponse:
    return await google_auth_mediator.login_google()


@router.get("/oauth/google/callback", status_code=status.HTTP_200_OK)
async def oauth_google_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_async_db),
    error: Optional[str] = Query(default=None),
):
    return await google_auth_mediator.oauth_google_callback(
        request=request,
        code=code,
        state=state,
        db=db,
        error=error,
    )
