from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.auth.service.users as user_service
from pumpkit.auth import mediator
from pumpkit.auth.dependencies import get_current_user
from pumpkit.auth.google_sign_in import GoogleSignIn, get_google_sign_in, require_google_sign_in
from pumpkit.auth.mailer import AuthMailer, get_auth_mailer
from pumpkit.auth.models import User
from pumpkit.auth.schemas import MagicLinkRequest, UserProfileResponse, UserProfileUpdate
from pumpkit.core.db.session import get_async_db
from pumpkit.core.rate_limit import limiter
from pumpkit.core.schemas import MessageResponse
from pumpkit.core.time import Clock, get_clock

# Tags are set per route: the Sign-in method and Session routes are "auth", the profile "users".
router = APIRouter()


@router.get(
    "/login/google",
    status_code=status.HTTP_200_OK,
    tags=["auth"],
    dependencies=[Depends(require_google_sign_in)],
)
async def start_google_sign_in() -> JSONResponse:
    return await mediator.start_google_sign_in()


@router.get(
    "/oauth/google/callback",
    status_code=status.HTTP_303_SEE_OTHER,
    tags=["auth"],
    dependencies=[Depends(require_google_sign_in)],
)
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
    return await mediator.oauth_google_callback(
        request=request,
        db=db,
        google_sign_in=google_sign_in,
        code=code,
        state=state,
        error=error,
    )


@router.post(
    "/login/magic-link/request",
    status_code=status.HTTP_200_OK,
    response_model=MessageResponse,
    tags=["auth"],
)
@limiter.limit("5/15minutes")
async def request_magic_link(
    request: Request,
    request_data: MagicLinkRequest,
    db: AsyncSession = Depends(get_async_db),
    mailer: AuthMailer = Depends(get_auth_mailer),
    clock: Clock = Depends(get_clock),
) -> MessageResponse:
    return await mediator.request_magic_link(
        email=request_data.email,
        request=request,
        db=db,
        mailer=mailer,
        now=clock(),
    )


@router.get("/login/magic-link", status_code=status.HTTP_303_SEE_OTHER, tags=["auth"])
@limiter.limit("20/minute")
async def complete_magic_link(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> RedirectResponse:
    # The browser lands here from an email link, so every outcome is a redirect.
    return await mediator.complete_magic_link(
        token=token,
        request=request,
        db=db,
        now=clock(),
    )


@router.get(
    "/login/magic-link/inbox-redirect",
    status_code=status.HTTP_303_SEE_OTHER,
    tags=["auth"],
)
@limiter.limit("60/minute")
async def magic_link_inbox_redirect(request: Request) -> RedirectResponse:
    return mediator.build_inbox_redirect_response()


@router.post("/refresh-token", status_code=status.HTTP_200_OK, tags=["auth"])
async def refresh_token(request: Request, db: AsyncSession = Depends(get_async_db)) -> JSONResponse:
    return await mediator.refresh_token(request=request, db=db)


@router.post("/logout", status_code=status.HTTP_200_OK, tags=["auth"])
async def logout(request: Request, db: AsyncSession = Depends(get_async_db)) -> JSONResponse:
    return await mediator.logout(request=request, db=db)


@router.get(
    "/users/me",
    response_model=UserProfileResponse,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
) -> UserProfileResponse:
    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        avatar_data_url=current_user.avatar_data_url,
    )


@router.patch(
    "/users/me",
    response_model=UserProfileResponse,
    status_code=status.HTTP_200_OK,
    tags=["users"],
)
async def update_current_user_profile(
    update: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> UserProfileResponse:
    """Apply only the fields present in the body; ``null`` clears a field (e.g. the avatar)."""

    current_user = await user_service.update_user_profile(
        db=db, user=current_user, changes=update.model_dump(exclude_unset=True)
    )
    await db.commit()
    await db.refresh(current_user)

    return UserProfileResponse(
        id=current_user.id,
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        avatar_data_url=current_user.avatar_data_url,
    )
