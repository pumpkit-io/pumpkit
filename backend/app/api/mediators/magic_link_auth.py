from datetime import datetime
from typing import Optional
from urllib.parse import quote

from fastapi import Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.magic_links as magic_links
import app.api.services.sessions as sessions
import app.api.services.users as user_service
from app.core.auth_mailer import AuthMailer, AuthMailerError
from app.core.config import settings
from app.core.logger import logger
from app.db.models import User
from app.schemas.common import MessageResponse

# Generic message returned by the request endpoint regardless of whether the
# email is registered or rate-limited, so it never reveals which emails have accounts.
_GENERIC_REQUEST_MESSAGE = "If an account exists for that email, we've sent you a sign-in link."


class RejectedMagicLinkError(Exception):
    """A Magic link that can't sign anyone in: unknown, already used or expired."""


async def request_magic_link(
    email: str,
    request: Request,
    db: AsyncSession,
    mailer: AuthMailer,
    now: datetime,
) -> MessageResponse:
    """
    Issue a one-time Magic link and email it to the User.

    Always returns a generic message to avoid disclosing account existence.
    If the email can't be sent, the link is invalidated so an immediate retry
    sends a new one, and `AuthMailerError` reaches the global handler.
    """
    user: Optional[User] = await user_service.get_user_by_email(db=db, email=email)
    issued = await magic_links.issue(
        db,
        email=email,
        user_id=user.id if user else None,
        client=sessions.ClientInfo.from_request(request),
        now=now,
    )
    if isinstance(issued, magic_links.CoolingDown):
        return MessageResponse(message=_GENERIC_REQUEST_MESSAGE)
    # Sanctioned early commit: persist the issued link before the external send,
    # so a fast double-click hits the cool-down instead of sending a second email.
    await db.commit()

    try:
        await mailer.send_magic_link(
            to=email,
            display_name=user.display_name if user else "",
            link_url=f"{settings.BACKEND_URL}/api/v1/login/magic-link?token={issued.token}",
            expires_in_minutes=issued.expires_in_minutes,
        )
    except AuthMailerError:
        # The email never left, so the link must not hold the cool-down.
        # Commit before re-raising: the request session rolls back on errors.
        await magic_links.invalidate(db, token=issued.token)
        await db.commit()
        raise

    return MessageResponse(message=_GENERIC_REQUEST_MESSAGE)


async def complete_magic_link(
    token: str,
    request: Request,
    db: AsyncSession,
    now: datetime,
) -> RedirectResponse:
    """
    Redeem a Magic link, sign the user in (creating the user row in the database
    if needed), and redirect to the frontend callback with the access token in
    the URL fragment + the refresh token in an HTTP-only cookie.
    """
    redeemed = await magic_links.redeem(db, token=token, now=now)
    if isinstance(redeemed, magic_links.RedemptionFailure):
        logger.warning("Magic link rejected: %s", redeemed.reason.value)
        raise RejectedMagicLinkError(redeemed.reason.value)

    # Resolve the User (found or created) from the email on the consumed Magic link row,
    # NEVER from anything in the click URL. Every Sign-in method resolves through the
    # same operation, so one email always reaches one User.
    user = await user_service.resolve_user_by_verified_email(db, redeemed.email)

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
