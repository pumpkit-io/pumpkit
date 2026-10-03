from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.auth_sessions as auth_sessions_mediator
from app.core.logger import logger
from app.db.session import get_async_db

router = APIRouter(tags=["auth"])


@router.post("/refresh-token", status_code=status.HTTP_200_OK)
async def refresh_token(request: Request, db: AsyncSession = Depends(get_async_db)) -> JSONResponse:
    try:
        return await auth_sessions_mediator.refresh_token(request=request, db=db)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during token refresh")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(request: Request, db: AsyncSession = Depends(get_async_db)) -> JSONResponse:
    try:
        return await auth_sessions_mediator.logout(request=request, db=db)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during user logout")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )
