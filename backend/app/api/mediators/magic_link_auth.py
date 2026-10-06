from datetime import datetime
from typing import Optional
from urllib.parse import quote

from fastapi import Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.magic_links as magic_links
import app.api.services.sessions as sessions
import app.api.services.users as user_service
from app.core.auth_mailer import AuthMailer, AuthMailerError, MagicLinkEmail
from app.core.config import settings
from app.core.exceptions import report_unexpected_exception
from app.core.logger import logger
from app.db.models import User
from app.schemas.common import MessageResponse

# Same message whether the email is registered or cooling down, so it never reveals accounts.
_GENERIC_REQUEST_MESSAGE = "If an account exists for that email, we've sent you a sign-in link."


async def request_magic_link(
    email: str,
    request: Request,
    db: AsyncSession,
    mailer: AuthMailer,
    now: datetime,
) -> MessageResponse:
    """
    Always returns a generic message, to avoid disclosing account existence.
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
            MagicLinkEmail(
                to=email,
                display_name=user.display_name if user else "",
                link_url=f"{settings.BACKEND_URL}/api/v1/login/magic-link?token={issued.token}",
                expires_in_minutes=issued.expires_in_minutes,
            )
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
    Always redirect: to the frontend callback with a new Session, or to the sign-in page with
    `invalid_magic_link`, `account_suspended` or `sign_in_failed`. An unexpected exception is
    reported and rolled back, so a failure halfway leaves no User behind.
    """
    try:
        return await _sign_in_with_magic_link(token=token, request=request, db=db, now=now)
    except Exception as exc:
        report_unexpected_exception(request, exc)
        await db.rollback()
        return sessions.sign_in_error_redirect("sign_in_failed")


async def _sign_in_with_magic_link(
    token: str,
    request: Request,
    db: AsyncSession,
    now: datetime,
) -> RedirectResponse:
    redeemed = await magic_links.redeem(db, token=token, now=now)
    if isinstance(redeemed, magic_links.RedemptionFailure):
        logger.warning("Magic link rejected: %s", redeemed.reason.value)
        return sessions.sign_in_error_redirect("invalid_magic_link")

    # Trust only the email on the consumed Magic link row, never the click URL.
    # Every Sign-in method resolves through this operation, so one email reaches one User.
    user = await user_service.resolve_user_by_verified_email(db, redeemed.email)

    result = await sessions.start(
        db,
        user=user,
        sign_in_method="magic_link",
        client=sessions.ClientInfo.from_request(request),
    )
    # Commit a refusal too, so the single-use Magic link stays consumed.
    # A refused User already exists (Suspended), so resolving them wrote nothing else.
    await db.commit()
    if isinstance(result, sessions.SessionRefusal):
        return result.as_sign_in_redirect()
    return result.as_callback_redirect("/auth/magic-link/callback")


def build_inbox_redirect_response() -> RedirectResponse:
    """Open Gmail filtered to the Magic link sender."""
    query = f"from:{settings.RESEND_NOREPLY_ADDRESS}"
    target = f"https://mail.google.com/mail/u/0/#search/{quote(query, safe='')}"
    return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)
