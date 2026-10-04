from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.sessions as sessions_mediator
from app.db.session import get_async_db

router = APIRouter(tags=["auth"])


@router.post("/refresh-token", status_code=status.HTTP_200_OK)
async def refresh_token(request: Request, db: AsyncSession = Depends(get_async_db)) -> JSONResponse:
    return await sessions_mediator.refresh_token(request=request, db=db)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(request: Request, db: AsyncSession = Depends(get_async_db)) -> JSONResponse:
    return await sessions_mediator.logout(request=request, db=db)
