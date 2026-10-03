import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote, urlencode

import resend
from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.auth_sessions as auth_sessions_service
import app.api.services.magic_link_auth as magic_link_auth_service
import app.api.services.users as user_service
from app.core.config import settings
from app.core.ids import ulid_with_prefix
from app.core.logger import logger
from app.core.security import (
    create_access_token,
    create_redirect_response,
    create_refresh_token,
    generate_token,
    hash_token,
)
from app.core.templates import templates_helper
from app.db.models import MagicLink, User
from app.schemas.common import MessageResponse

# Generic message returned by the request endpoint regardless of whether the
# email is registered or rate-limited. Same enumeration-protection pattern as
# the existing password reset flow.
_GENERIC_REQUEST_MESSAGE = "If an account exists for that email, we've sent you a sign-in link."

# In-app cool-down between consecutive requests for the same email, in seconds.
_REQUEST_COOLDOWN_SECONDS = 60

# Logo embedded inline in the magic-link email via CID. Loaded once at import
# time so we don't re-read + re-encode the file on every send. Replace
# templates/emails/assets/logo.png with your own logo.
_LOGO_PATH = (
    Path(__file__).resolve().parent.parent.parent / "templates" / "emails" / "assets" / "logo.png"
)
_LOGO_CONTENT_ID = "app-logo"
_LOGO_BASE64 = base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")


async def request_magic_link(
    email: str,
    request: Request,
    db: AsyncSession,
) -> MessageResponse:
    """
    Generate a one-time magic-link token, store its hash, and email it to the user.

    The clear-text token only ever exists in the email body and the user's URL bar.
    Always returns a generic message to avoid disclosing account existence.
    """

    # Cool-down: bail if a link was just issued for this email
    latest = await magic_link_auth_service.get_latest_magic_link_by_email(db=db, email=email)
    if latest:
        seconds_since_last = (datetime.now(timezone.utc) - latest.sent_at).total_seconds()
        if seconds_since_last < _REQUEST_COOLDOWN_SECONDS:
            return MessageResponse(message=_GENERIC_REQUEST_MESSAGE)

    user: Optional[User] = await user_service.get_user_by_email(db=db, email=email)

    # Invalidate any outstanding unconsumed links for this email
    await magic_link_auth_service.invalidate_magic_links_for_email(db=db, email=email)

    # Generate token + hash
    token = generate_token(num_bytes=settings.MAGIC_LINK_TOKEN_NUM_BYTES)
    token_hash = hash_token(token)

    # Persist the magic link row BEFORE sending the email so the cool-down check above can see it on a fast double-click.
    magic_link = MagicLink(
        user_id=user.id if user else None,
        email=email,
        token_hash=token_hash,
        expires_at=datetime.now(timezone.utc)
        + timedelta(minutes=settings.MAGIC_LINK_TOKEN_DURATION_MINUTES),
        requester_ip=request.client.host if request.client else None,
        requester_user_agent=request.headers.get("user-agent"),
    )
    await magic_link_auth_service.create_magic_link(db=db, magic_link=magic_link)

    # Send the email with the magic link.
    magic_url = f"{settings.BACKEND_URL}/api/v1/login/magic-link?token={token}"
    try:
        resend.Emails.send(
            {
                "from": f"{settings.APP_NAME} <{settings.RESEND_NOREPLY_ADDRESS}>",
                "to": [email],
                "subject": f"Sign in to {settings.APP_NAME}",
                "html": templates_helper.render_template(
                    "emails/magic_link.html",
                    display_name=user.display_name if user else "",
                    magic_url=magic_url,
                    expires_in_minutes=settings.MAGIC_LINK_TOKEN_DURATION_MINUTES,
                    app_name=settings.APP_NAME,
                    logo_cid=_LOGO_CONTENT_ID,
                ),
                "attachments": [
                    {
                        "filename": "logo.png",
                        "content": _LOGO_BASE64,
                        "content_type": "image/png",
                        "content_id": _LOGO_CONTENT_ID,
                    }
                ],
            }
        )
    except Exception:
        logger.exception("Failed to send magic-link email to %s", email)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="We couldn't send the sign-in link. Please try again later.",
        )

    return MessageResponse(message=_GENERIC_REQUEST_MESSAGE)


async def complete_magic_link(
    token: str,
    request: Request,
    db: AsyncSession,
) -> RedirectResponse:
    """
    Validate a magic-link token, sign the user in (creating the user row in the database
    if needed), and redirect to the frontend callback with the access token in
    the URL fragment + the refresh token in an HTTP-only cookie.
    """

    if not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Magic link token is required."
        )

    # Get and validate the magic link by the token hash.
    token_hash = hash_token(token)
    magic_link = await magic_link_auth_service.get_magic_link_by_token_hash(
        db=db, token_hash=token_hash
    )

    if not magic_link:
        logger.error("Magic link login failed: invalid token (hash=%s...)", token_hash[:8])
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired magic link."
        )

    if magic_link.consumed_at:
        logger.error("Magic link login failed: token already used (id=%s)", magic_link.id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="This magic link has already been used."
        )

    if magic_link.expires_at <= datetime.now(timezone.utc):
        logger.error("Magic link login failed: token expired (id=%s)", magic_link.id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="This magic link has expired."
        )

    # Atomically consume the row to prevent race conditions
    consumed = await magic_link_auth_service.atomically_consume_magic_link(
        db=db, token_hash=token_hash
    )
    if consumed is None:
        # Race: another concurrent request consumed it
        logger.error("Magic link login failed: token consumed in race (id=%s)", magic_link.id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="This magic link has already been used."
        )

    # Resolve the user and create it in the database if it doesn't exist yet.
    # The email used for identity resolution comes from the consumed MagicLink row,
    # NEVER from anything in the click URL - we cannot fully trust it.
    # Same email always maps to the same User row, regardless of how that row
    # was originally created (e.g. Google OAuth, email/password, prior magic link).
    user = await user_service.get_user_by_email(db=db, email=consumed.email)
    if user is None:
        local_part = consumed.email.split("@", 1)[0]
        user = User(
            id=ulid_with_prefix("user"),
            email=consumed.email,
            display_name=local_part,
            first_name=None,
            last_name=None,
            is_admin=False,
        )
        await user_service.create_user(db=db, user=user)

    # Create access and refresh tokens
    access_token = create_access_token(
        data={"sub": user.id, "email": user.email},
    )
    refresh_token = create_refresh_token(
        data={"sub": user.id, "email": user.email},
    )
    await auth_sessions_service.create_auth_session(
        db=db,
        user_id=user.id,
        refresh_token=refresh_token,
        auth_method="magic_link",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    # Build the redirect to the frontend callback page
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
    )
    frontend_redirect_params = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_at": expires_at.isoformat(),
    }
    frontend_redirect_url = (
        f"{settings.FRONTEND_URL}/auth/magic-link/callback#{urlencode(frontend_redirect_params)}"
    )
    return create_redirect_response(
        redirect_url=frontend_redirect_url,
        refresh_token=refresh_token,
    )


def build_inbox_redirect_response() -> RedirectResponse:
    """
    303-redirect the browser to a Gmail search URL filtered by our
    magic-link sender.
    """
    query = f"from:{settings.RESEND_NOREPLY_ADDRESS}"
    target = f"https://mail.google.com/mail/u/0/#search/{quote(query, safe='')}"
    return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)
