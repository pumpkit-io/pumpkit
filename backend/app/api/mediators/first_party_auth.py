from datetime import datetime, timedelta, timezone
from typing import Optional

import resend
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.auth_sessions as auth_sessions_service
import app.api.services.first_party_auth as first_party_auth_service
import app.api.services.users as user_service
from app.core.config import settings
from app.core.ids import ulid_with_prefix
from app.core.logger import logger
from app.core.security import (
    create_access_token,
    create_auth_response,
    create_refresh_token,
    decrypt,
    encrypt,
    generate_token,
    hash_password,
    hash_token,
)
from app.core.templates import templates_helper
from app.db.models import (
    EmailVerification,
    FirstPartyAuth,
    PasswordReset,
    User,
)
from app.schemas.common import MessageResponse
from app.schemas.first_party_auth import (
    PasswordResetCompleteResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    SignupResponse,
    UserLogin,
    UserSignup,
)


async def signup(user: UserSignup, db: AsyncSession) -> SignupResponse:
    """
    Sign up a new user using email and password. A confirmation email is sent
    to the user's email address. The user cannot sign in until they have confirmed their
    email address.

    If the user already exists (e.g. from Google OAuth) but has no email/password
    credentials, this will link email/password authentication to the existing account.
    """

    # Check if a user with this email already exists
    existing_user: Optional[User] = await user_service.get_user_by_email(db=db, email=user.email)

    if existing_user:
        # Check if the user already created an account with email/password credentials
        existing_fpa = await first_party_auth_service.get_first_party_auth_by_user_id(
            db=db, user_id=existing_user.id
        )

        if existing_fpa and existing_fpa.is_email_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered."
            )

        if existing_fpa and not existing_fpa.is_email_verified:
            # User signed up with email/password before but never confirmed their email.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered. We sent you an email to confirm your account before signing in.",
            )

        if existing_fpa is None:
            # User exists (e.g. from Google OAuth) but has no first-party auth.
            # Create one to link email/password credentials to the existing account.
            first_party_auth = FirstPartyAuth(
                id=ulid_with_prefix("first_party_auth"),
                user_id=existing_user.id,
                password_hash=hash_password(user.password),
            )

            await _create_email_verification_and_send(db=db, user=existing_user)

            await first_party_auth_service.create_first_party_auth(
                db=db, first_party_auth=first_party_auth
            )

            return SignupResponse(
                message="Account created successfully! Please check your email to confirm your account before signing in.",
                email=existing_user.email,
            )

    # Create the new user
    new_user_id = ulid_with_prefix("user")

    new_user = User(
        id=new_user_id,
        email=user.email,
        display_name=user.first_name,
        first_name=user.first_name,
        last_name=user.last_name,
    )

    await user_service.create_user(db=db, user=new_user)

    # Record the user's password for first-party authentication
    first_party_auth = FirstPartyAuth(
        id=ulid_with_prefix("first_party_auth"),
        user_id=new_user_id,
        password_hash=hash_password(user.password),
    )

    await first_party_auth_service.create_first_party_auth(db=db, first_party_auth=first_party_auth)

    # Create email verification and send confirmation email
    await _create_email_verification_and_send(db=db, user=new_user)

    # Return success feedback - do not log the user in until they have confirmed their email
    return SignupResponse(
        message="Account created successfully! Please check your email to confirm your account before signing in.",
        email=new_user.email,
    )


async def confirm_email(token: str, db: AsyncSession) -> RedirectResponse:
    """
    Confirm user email address using the verification token.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Verification token is required."
        )

    # Verify the token
    token_hash = hash_token(token)

    email_verification: Optional[
        EmailVerification
    ] = await first_party_auth_service.get_email_verification_by_token_hash(
        db=db, token_hash=token_hash
    )

    if not email_verification:
        logger.error("Email confirmation failed: invalid token (hash=%s...)", token_hash[:8])
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token."
        )

    if email_verification.consumed_at:
        logger.error(
            "Email confirmation failed: token already used (user_id=%s)", email_verification.user_id
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This verification token has already been used.",
        )

    if email_verification.expires_at <= datetime.now(timezone.utc):
        logger.error(
            "Email confirmation failed: token expired (user_id=%s)", email_verification.user_id
        )
        # TODO: if the verification token is expired, should we generate and send a new one to the user automatically?
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Verification token has expired."
        )

    confirmed = (
        await first_party_auth_service.atomically_consume_email_verification_and_verify_user(
            db=db, token_hash=token_hash
        )
    )

    if not confirmed:
        # Race condition: another concurrent request consumed the token
        logger.error(
            "Email confirmation failed: token already used (race condition, user_id=%s)",
            email_verification.user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This verification token has already been used.",
        )

    # Redirect to login page with success message and pre-filled email
    login_url = f"{settings.FRONTEND_URL}/login?email_confirmed=true"

    response = RedirectResponse(
        url=login_url,
        status_code=status.HTTP_303_SEE_OTHER,
    )

    # Pass the email via an encrypted, short-lived cookie so the frontend
    # can pre-fill the login form without exposing the email in the URL.
    response.set_cookie(
        key="confirmed_email",
        value=encrypt(email_verification.email_to_verify),
        max_age=settings.EMAIL_VERIFICATION_COOKIE_DURATION_SECONDS,
        httponly=True,
        secure=settings.is_env_production(),
        samesite="lax",
        path="/",
    )

    return response


async def get_confirmed_email(request: Request) -> JSONResponse:
    """
    Read and decrypt the cookie returned by the email verification process to get
    the confirmed email address.
    """
    encrypted_email = request.cookies.get("confirmed_email")
    if not encrypted_email:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No confirmed email found."
        )

    email = decrypt(encrypted_email)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid confirmed email."
        )

    response = JSONResponse(content={"email": email})
    # Delete the cookie after reading it to prevent it from being used again
    response.delete_cookie(key="confirmed_email", path="/")
    return response


async def login(request: Request, user: UserLogin, db: AsyncSession) -> JSONResponse:
    """
    Login a user with email and password.
    """
    # Authenticate user
    authenticated_user = await first_party_auth_service.authenticate_user(
        db=db, email=user.email, password=user.password
    )

    if not authenticated_user:
        logger.warning("Login failed: invalid credentials (email=%s)", user.email)

        # Check if user exists but email is not verified
        existing_user = await user_service.get_user_by_email(db=db, email=user.email)
        if existing_user and not await first_party_auth_service.is_email_verified(
            db=db, user_id=existing_user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Please check your email to verify your account before signing in",
                headers={"WWW-Authenticate": "Bearer"},
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token
    access_token = create_access_token(
        data={
            "sub": authenticated_user.id,
            "email": authenticated_user.email,
        },
    )

    # Create and store refresh token
    refresh_token = create_refresh_token(
        data={
            "sub": authenticated_user.id,
            "email": authenticated_user.email,
        },
    )

    await auth_sessions_service.create_auth_session(
        db=db,
        user_id=authenticated_user.id,
        refresh_token=refresh_token,
        auth_method="local",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    login_response: JSONResponse = create_auth_response(
        access_token=access_token,
        refresh_token=refresh_token,
    )

    return login_response


async def request_password_reset(
    request_data: PasswordResetRequest, db: AsyncSession
) -> MessageResponse:
    """
    Initiate a password reset by sending a one-time link to the user.
    """

    generic_message = "If an account with that email exists, we'll send an email with a link to reset your password shortly."

    user = await user_service.get_user_by_email(db=db, email=request_data.email)

    if not user:
        # Always return the same message to avoid disclosing account existence
        return MessageResponse(message=generic_message)

    first_party_auth = await first_party_auth_service.get_first_party_auth_by_user_id(
        db=db, user_id=user.id
    )
    if not first_party_auth:
        return MessageResponse(message=generic_message)

    # Invalidate any outstanding tokens for this user before issuing a new one
    await first_party_auth_service.invalidate_password_resets_for_user(db=db, user_id=user.id)

    token = generate_token(num_bytes=settings.PASSWORD_RESET_TOKEN_NUM_BYTES)
    token_hash = hash_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(
        hours=settings.PASSWORD_RESET_TOKEN_DURATION_HOURS
    )

    password_reset = PasswordReset(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )

    await first_party_auth_service.create_password_reset(db=db, password_reset=password_reset)

    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
    display_name = user.display_name or user.first_name or user.email

    try:
        resend.Emails.send(
            {
                "from": f"{settings.APP_NAME} <{settings.RESEND_NOREPLY_ADDRESS}>",
                "to": [user.email],
                "subject": f"Reset your {settings.APP_NAME} password",
                "html": templates_helper.render_template(
                    "emails/reset_password.html",
                    display_name=display_name,
                    reset_url=reset_url,
                    token_expiration_hours=settings.PASSWORD_RESET_TOKEN_DURATION_HOURS,
                ),
            }
        )
    except Exception:  # noqa: BLE001 - we just need to log and re-raise a generic error
        logger.exception("Failed to send password reset email")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="We couldn't send the reset email. Please try again later.",
        )

    return MessageResponse(message=generic_message)


async def resend_confirmation_email(email: str, db: AsyncSession) -> MessageResponse:
    """
    Resend a confirmation email to a user who hasn't verified their email yet.
    Always returns a generic message to avoid disclosing account existence.
    """

    generic_message = "If an unverified account with that email exists, we just sent a new email to verify your account."

    user = await user_service.get_user_by_email(db=db, email=email)
    if not user:
        return MessageResponse(message=generic_message)

    first_party_auth = await first_party_auth_service.get_first_party_auth_by_user_id(
        db=db, user_id=user.id
    )
    if not first_party_auth or first_party_auth.is_email_verified:
        return MessageResponse(message=generic_message)

    # Rate limit: don't send if last verification email was sent less than 60 seconds ago
    latest_verification = await first_party_auth_service.get_latest_email_verification_by_user_id(
        db=db, user_id=user.id
    )
    if latest_verification:
        seconds_since_last = (
            datetime.now(timezone.utc) - latest_verification.sent_at
        ).total_seconds()
        if seconds_since_last < 60:
            return MessageResponse(message=generic_message)

    await _create_email_verification_and_send(db=db, user=user)

    return MessageResponse(message=generic_message)


async def reset_password(
    request_data: PasswordResetConfirm, db: AsyncSession
) -> PasswordResetCompleteResponse:
    """
    Complete a password reset given a valid token and new password.
    """

    if not request_data.token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Reset token is required."
        )

    token_hash = hash_token(request_data.token)
    password_reset = await first_party_auth_service.get_password_reset_by_token_hash(
        db=db, token_hash=token_hash
    )

    if not password_reset:
        logger.error("Password reset failed: invalid token (hash=%s...)", token_hash[:8])
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired password reset link.",
        )

    if password_reset.consumed_at:
        logger.error(
            "Password reset failed: token already used (user_id=%s)", password_reset.user_id
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This password reset link has already been used.",
        )

    if password_reset.expires_at <= datetime.now(timezone.utc):
        logger.error("Password reset failed: token expired (user_id=%s)", password_reset.user_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Password reset link has expired."
        )

    user = await user_service.get_user_by_id(db=db, user_id=password_reset.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to reset password for this account.",
        )

    new_password_hash = hash_password(request_data.new_password)
    consumed = await first_party_auth_service.atomically_consume_password_reset_and_update_password(
        db=db,
        token_hash=token_hash,
        password_hash=new_password_hash,
    )

    if not consumed:
        # Race condition: another concurrent request consumed the token
        logger.error(
            "Password reset failed: token already used (race condition, user_id=%s)",
            password_reset.user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This password reset link has already been used.",
        )

    await auth_sessions_service.revoke_all_user_auth_sessions(db=db, user_id=user.id)

    return PasswordResetCompleteResponse(
        message="Password updated successfully. You can now sign in.",
        email=user.email,
    )


async def _create_email_verification_and_send(
    db: AsyncSession,
    user: User,
) -> None:
    """
    Create an email verification record and send the confirmation email.
    """
    verification_token = generate_token(num_bytes=settings.EMAIL_VERIFICATION_TOKEN_NUM_BYTES)
    verification_token_hash = hash_token(verification_token)

    new_email_verification = EmailVerification(
        user_id=user.id,
        email_to_verify=user.email,
        token_hash=verification_token_hash,
        expires_at=datetime.now(timezone.utc)
        + timedelta(hours=settings.EMAIL_VERIFICATION_TOKEN_DURATION_HOURS),
    )

    try:
        # Send the confirmation email with the verification link
        resend.Emails.send(
            {
                "from": f"{settings.APP_NAME} <{settings.RESEND_NOREPLY_ADDRESS}>",
                "to": [user.email],
                "subject": "Confirm your email",
                "html": templates_helper.render_template(
                    "emails/confirm_email.html",
                    display_name=user.display_name,
                    confirm_url=f"{settings.FRONTEND_URL}/confirm-email?token={verification_token}",
                ),
            }
        )
    except Exception:
        logger.exception("Failed to send confirmation email to %s", user.email)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Your account was created but we couldn't send the confirmation email. Please try resending it.",
        )

    # Store the email verification record in the database.
    # Doing this after the confirmation email is sent to avoid creating unused records if the email fails to send
    await first_party_auth_service.create_email_verification(
        db=db, email_verification=new_email_verification
    )
