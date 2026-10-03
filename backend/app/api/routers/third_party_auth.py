from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.third_party_auth as third_party_auth_mediator
from app.core.logger import logger
from app.db.session import get_async_db

router = APIRouter(tags=["auth"])


@router.get("/login/google", status_code=status.HTTP_200_OK)
async def login_google() -> JSONResponse:
    try:
        return await third_party_auth_mediator.login_google()
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during user login via Google")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )


@router.get("/oauth/google/callback", status_code=status.HTTP_200_OK)
async def oauth_google_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_async_db),
    error: Optional[str] = Query(default=None),
):
    try:
        return await third_party_auth_mediator.oauth_google_callback(
            request=request,
            code=code,
            state=state,
            db=db,
            error=error,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during the callback for user login via Google")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )
