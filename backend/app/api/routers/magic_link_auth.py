from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.magic_link_auth as magic_link_auth_mediator
from app.core.auth_mailer import AuthMailer, get_auth_mailer
from app.core.clock import Clock, get_clock
from app.core.config import settings
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
    mailer: AuthMailer = Depends(get_auth_mailer),
    clock: Clock = Depends(get_clock),
) -> MessageResponse:
    return await magic_link_auth_mediator.request_magic_link(
        email=request_data.email,
        request=request,
        db=db,
        mailer=mailer,
        now=clock(),
    )


@router.get("/login/magic-link", status_code=status.HTTP_303_SEE_OTHER)
@limiter.limit("20/minute")
async def login_magic_link(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> RedirectResponse:
    # The browser lands here from an email link, so a rejected Magic link goes
    # to the login error page instead of JSON. Any other error propagates.
    try:
        return await magic_link_auth_mediator.complete_magic_link(
            token=token,
            request=request,
            db=db,
            now=clock(),
        )
    except magic_link_auth_mediator.RejectedMagicLinkError:
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
    return magic_link_auth_mediator.build_inbox_redirect_response()
