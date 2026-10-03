from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.magic_link_auth as magic_link_auth_mediator
from app.core.config import settings
from app.core.logger import logger
from app.core.rate_limit import limiter
from app.db.session import get_async_db
from app.schemas.common import MessageResponse
from app.schemas.magic_link_auth import MagicLinkRequest

router = APIRouter(tags=["auth"])


@router.post(
    "/login/magic-link/request",
    status_code=status.HTTP_200_OK,
    response_model=MessageResponse,
)
@limiter.limit("5/15minutes")
async def request_magic_link(
    request: Request,
    request_data: MagicLinkRequest,
    db: AsyncSession = Depends(get_async_db),
) -> MessageResponse:
    try:
        return await magic_link_auth_mediator.request_magic_link(
            email=request_data.email,
            request=request,
            db=db,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during magic link request")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )


@router.get("/login/magic-link", status_code=status.HTTP_303_SEE_OTHER)
@limiter.limit("20/minute")
async def login_magic_link(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_async_db),
) -> RedirectResponse:
    try:
        return await magic_link_auth_mediator.complete_magic_link(
            token=token,
            request=request,
            db=db,
        )
    except HTTPException:
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/login?error=invalid_magic_link",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    except Exception:
        logger.exception("Unexpected error during magic link completion")
        return RedirectResponse(
            url=f"{settings.FRONTEND_URL}/login?error=invalid_magic_link",
            status_code=status.HTTP_303_SEE_OTHER,
        )


@router.get(
    "/login/magic-link/inbox-redirect",
    status_code=status.HTTP_303_SEE_OTHER,
)
@limiter.limit("60/minute")
async def magic_link_inbox_redirect(request: Request) -> RedirectResponse:
    try:
        return magic_link_auth_mediator.build_inbox_redirect_response()
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error building magic-link inbox redirect")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )
