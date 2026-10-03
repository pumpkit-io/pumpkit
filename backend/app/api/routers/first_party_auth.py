from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.mediators.first_party_auth as first_party_auth_mediator
from app.core.logger import logger
from app.core.rate_limit import limiter
from app.db.session import get_async_db
from app.schemas.common import MessageResponse
from app.schemas.first_party_auth import (
    PasswordResetCompleteResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    ResendConfirmationEmailRequest,
    SignupResponse,
    UserLogin,
    UserSignup,
)

router = APIRouter(tags=["auth"])


@router.post("/signup", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def signup(
    request: Request, user: UserSignup, db: AsyncSession = Depends(get_async_db)
) -> SignupResponse:
    try:
        return await first_party_auth_mediator.signup(user=user, db=db)
    except HTTPException:
        raise
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered.",
        )
    except Exception:
        logger.exception("Unexpected error during user signup")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )


@router.get("/confirm-email", status_code=status.HTTP_303_SEE_OTHER)
@limiter.limit("10/minute")
async def confirm_email(
    request: Request, token: str, db: AsyncSession = Depends(get_async_db)
) -> RedirectResponse:
    try:
        return await first_party_auth_mediator.confirm_email(token=token, db=db)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during user email confirmation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )


@router.get("/confirmed-email", status_code=status.HTTP_200_OK)
async def get_confirmed_email(request: Request) -> JSONResponse:
    try:
        return await first_party_auth_mediator.get_confirmed_email(request=request)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during user email confirmation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )


@router.post(
    "/resend-confirmation-email",
    status_code=status.HTTP_200_OK,
    response_model=MessageResponse,
)
@limiter.limit("5/15minutes")
async def resend_confirmation_email(
    request: Request,
    request_data: ResendConfirmationEmailRequest,
    db: AsyncSession = Depends(get_async_db),
) -> MessageResponse:
    try:
        return await first_party_auth_mediator.resend_confirmation_email(
            email=request_data.email,
            db=db,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during resend confirmation email")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )


@router.post("/login", status_code=status.HTTP_200_OK)
@limiter.limit("10/15minutes")
async def login(
    request: Request, user: UserLogin, db: AsyncSession = Depends(get_async_db)
) -> JSONResponse:
    try:
        return await first_party_auth_mediator.login(request=request, user=user, db=db)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during user login")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_200_OK,
    response_model=MessageResponse,
)
@limiter.limit("5/15minutes")
async def request_password_reset(
    request: Request,
    request_data: PasswordResetRequest,
    db: AsyncSession = Depends(get_async_db),
) -> MessageResponse:
    try:
        return await first_party_auth_mediator.request_password_reset(
            request_data=request_data,
            db=db,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during password reset request")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_200_OK,
    response_model=PasswordResetCompleteResponse,
)
async def reset_password(
    request_data: PasswordResetConfirm,
    db: AsyncSession = Depends(get_async_db),
) -> PasswordResetCompleteResponse:
    try:
        return await first_party_auth_mediator.reset_password(
            request_data=request_data,
            db=db,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during password reset confirmation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Something went wrong. Please try again later or contact us for support.",
        )
