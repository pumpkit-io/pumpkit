from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

from fastapi import Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.magic_link_auth as magic_link_auth_service
import app.api.services.sessions as sessions
import app.api.services.users as user_service
from app.core.auth_mailer import AuthMailer, AuthMailerError
from app.core.config import settings
from app.core.datetimes import as_utc
from app.core.ids import ulid_with_prefix
from app.core.logger import logger
from app.core.security import generate_token, hash_token
from app.db.models import MagicLink, User
from app.schemas.common import MessageResponse

# Generic message returned by the request endpoint regardless of whether the
# email is registered or rate-limited, so it never reveals which emails have accounts.
_GENERIC_REQUEST_MESSAGE = "If an account exists for that email, we've sent you a sign-in link."

# In-app cool-down between consecutive requests for the same email, in seconds.
_REQUEST_COOLDOWN_SECONDS = 60


class RejectedMagicLinkError(Exception):
    """A Magic link that can't sign anyone in: missing, unknown, already used or expired."""


async def request_magic_link(
    email: str,
    request: Request,
    db: AsyncSession,
    mailer: AuthMailer,
) -> MessageResponse:
    """
    Issue a one-time Magic link, store its hash, and email it to the User.

    The clear-text token only ever exists in the email body and the user's URL bar.
    Always returns a generic message to avoid disclosing account existence.
    If the email can't be sent, the link is discarded so an immediate retry
    sends a new one, and `AuthMailerError` reaches the global handler.
    """
    now = datetime.now(timezone.utc)

    # Cool-down: bail if a link was just issued for this email
    latest = await magic_link_auth_service.get_latest_magic_link_by_email(db=db, email=email)
    if latest:
        seconds_since_last = (now - as_utc(latest.sent_at)).total_seconds()
        if seconds_since_last < _REQUEST_COOLDOWN_SECONDS:
            return MessageResponse(message=_GENERIC_REQUEST_MESSAGE)

    user: Optional[User] = await user_service.get_user_by_email(db=db, email=email)

    # Invalidate any outstanding unconsumed links for this email
    await magic_link_auth_service.invalidate_magic_links_for_email(db=db, email=email)

    # Generate token + hash
    token = generate_token(num_bytes=settings.MAGIC_LINK_TOKEN_NUM_BYTES)
    token_hash = hash_token(token)

    magic_link = MagicLink(
        user_id=user.id if user else None,
        email=email,
        token_hash=token_hash,
        sent_at=now,
        expires_at=now + timedelta(minutes=settings.MAGIC_LINK_TOKEN_DURATION_MINUTES),
        requester_ip=request.client.host if request.client else None,
        requester_user_agent=request.headers.get("user-agent"),
    )
    await magic_link_auth_service.create_magic_link(db=db, magic_link=magic_link)
    # Sanctioned early commit: persist the issued link before the external send,
    # so a fast double-click hits the cool-down instead of sending a second email.
    await db.commit()

    magic_url = f"{settings.BACKEND_URL}/api/v1/login/magic-link?token={token}"
    try:
        await mailer.send_magic_link(
            to=email,
            display_name=user.display_name if user else "",
            link_url=magic_url,
            expires_in_minutes=settings.MAGIC_LINK_TOKEN_DURATION_MINUTES,
        )
    except AuthMailerError:
        # The email never left, so the link must not hold the cool-down.
        # Commit before re-raising: the request session rolls back on errors.
        await magic_link_auth_service.discard_unsent_magic_link(db=db, magic_link=magic_link)
        await db.commit()
        raise

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
        raise RejectedMagicLinkError("Magic link token is required.")

    # Get and validate the magic link by the token hash.
    token_hash = hash_token(token)
    magic_link = await magic_link_auth_service.get_magic_link_by_token_hash(
        db=db, token_hash=token_hash
    )

    if not magic_link:
        logger.error("Magic link login failed: invalid token (hash=%s...)", token_hash[:8])
        raise RejectedMagicLinkError("Invalid or expired magic link.")

    if magic_link.consumed_at:
        logger.error("Magic link login failed: token already used (id=%s)", magic_link.id)
        raise RejectedMagicLinkError("This magic link has already been used.")

    if as_utc(magic_link.expires_at) <= datetime.now(timezone.utc):
        logger.error("Magic link login failed: token expired (id=%s)", magic_link.id)
        raise RejectedMagicLinkError("This magic link has expired.")

    # Atomically consume the row to prevent race conditions
    consumed = await magic_link_auth_service.atomically_consume_magic_link(
        db=db, token_hash=token_hash
    )
    if consumed is None:
        # Race: another concurrent request consumed it
        logger.error("Magic link login failed: token consumed in race (id=%s)", magic_link.id)
        raise RejectedMagicLinkError("This magic link has already been used.")

    # Resolve the user and create it in the database if it doesn't exist yet.
    # The email used for identity resolution comes from the consumed MagicLink row,
    # NEVER from anything in the click URL - we cannot fully trust it.
    # Same email always maps to the same User row, regardless of how that row
    # was originally created (e.g. Google OAuth or a prior magic link).
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

    result = await sessions.start(
        db,
        user=user,
        sign_in_method="magic_link",
        client=sessions.ClientInfo.from_request(request),
    )
    await db.commit()
    if isinstance(result, sessions.SessionRefusal):
        return result.as_sign_in_redirect()
    return result.as_callback_redirect("/auth/magic-link/callback")


def build_inbox_redirect_response() -> RedirectResponse:
    """
    303-redirect the browser to a Gmail search URL filtered by our
    magic-link sender.
    """
    query = f"from:{settings.RESEND_NOREPLY_ADDRESS}"
    target = f"https://mail.google.com/mail/u/0/#search/{quote(query, safe='')}"
    return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)
