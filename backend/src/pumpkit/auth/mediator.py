import base64
import binascii
import hashlib
import json
import re
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.auth.service.api_keys as api_keys
import pumpkit.auth.service.google_identities as google_identities_service
import pumpkit.auth.service.magic_links as magic_links
import pumpkit.auth.service.sessions as sessions
import pumpkit.auth.service.users as user_service
from pumpkit.auth.google_config import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GOOGLE_CODE_VERIFIER_COOKIE,
    GOOGLE_NONCE_COOKIE,
    GOOGLE_SIGN_IN_SCOPES,
    GOOGLE_SIGN_IN_STATE_COOKIE,
)
from pumpkit.auth.google_sign_in import GoogleSignIn, GoogleSignInError
from pumpkit.auth.mailer import AuthMailer, AuthMailerError, MagicLinkEmail
from pumpkit.auth.models import ApiKey, User
from pumpkit.auth.schemas import ApiKeyCreatedResponse, ApiKeyResponse, ApiKeysListResponse
from pumpkit.auth.sign_up_allowlist import EMAIL_NOT_ALLOWED, EmailNotAllowedError, may_sign_in
from pumpkit.core.config import settings
from pumpkit.core.errors import report_unexpected_exception
from pumpkit.core.logging import logger
from pumpkit.core.schemas import MessageResponse
from pumpkit.core.security import (
    decode_payload,
    encode_payload,
    generate_token,
)
from pumpkit.core.time import as_utc

# The `flow` the state carries, so a state minted for another Google flow can't sign in.
_SIGN_IN_FLOW = "sign_in"

# The single-use state, nonce and PKCE verifier cookies of a Google sign-in.
_GOOGLE_COOKIES = (GOOGLE_SIGN_IN_STATE_COOKIE, GOOGLE_NONCE_COOKIE, GOOGLE_CODE_VERIFIER_COOKIE)


async def start_google_sign_in() -> JSONResponse:
    """
    Return Google's authorization URL.
    The response sets the state, nonce and PKCE verifier cookies the callback checks.
    """
    state_payload = {
        "flow": _SIGN_IN_FLOW,
        "nonce": generate_token(num_bytes=settings.GOOGLE_NONCE_TOKEN_NUM_BYTES),
    }
    state = encode_payload(state_payload)
    nonce = generate_token(num_bytes=settings.GOOGLE_NONCE_TOKEN_NUM_BYTES)
    code_verifier = generate_token(num_bytes=settings.GOOGLE_CODE_VERIFIER_TOKEN_NUM_BYTES)

    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )

    query_params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.google_oauth_redirect_uri(),
        "response_type": "code",
        "scope": " ".join(GOOGLE_SIGN_IN_SCOPES),
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
    }

    authorization_url = f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode(query_params)}"

    response = JSONResponse(content={"url": authorization_url})

    for key, value in zip(_GOOGLE_COOKIES, (state, nonce, code_verifier), strict=True):
        response.set_cookie(
            value=value,
            max_age=settings.GOOGLE_COOKIE_MAX_AGE_SECONDS,
            **_google_cookie_attributes(key),
        )

    return response


async def oauth_google_callback(
    request: Request,
    db: AsyncSession,
    google_sign_in: GoogleSignIn,
    code: Optional[str],
    state: Optional[str],
    error: Optional[str],
) -> RedirectResponse:
    """
    Always redirect: to the frontend callback with a new Session, or to the sign-in page
    with `sign_in_failed`, `account_suspended` or `email_not_allowed`. An unexpected exception is reported and
    rolled back, so a failure halfway leaves no User or Google identity behind.
    """
    try:
        response = await _sign_in_with_google(
            request=request,
            db=db,
            google_sign_in=google_sign_in,
            code=code,
            state=state,
            error=error,
        )
    except Exception as exc:
        report_unexpected_exception(request, exc)
        await db.rollback()
        response = sessions.sign_in_error_redirect("sign_in_failed")
    _delete_google_cookies(response)
    return response


async def _sign_in_with_google(
    request: Request,
    db: AsyncSession,
    google_sign_in: GoogleSignIn,
    code: Optional[str],
    state: Optional[str],
    error: Optional[str],
) -> RedirectResponse:
    if error:
        logger.warning("Google sign-in returned an error: %s", error)
        return sessions.sign_in_error_redirect("sign_in_failed")
    if not code or not state:
        logger.warning("Google sign-in callback without a code or state")
        return sessions.sign_in_error_redirect("sign_in_failed")

    # The state must be the one this browser was given, for the sign-in flow (CSRF).
    if (
        state != request.cookies.get(GOOGLE_SIGN_IN_STATE_COOKIE)
        or _state_flow(state) != _SIGN_IN_FLOW
    ):
        logger.warning("Google sign-in state mismatch")
        return sessions.sign_in_error_redirect("sign_in_failed")

    code_verifier = request.cookies.get(GOOGLE_CODE_VERIFIER_COOKIE)
    nonce = request.cookies.get(GOOGLE_NONCE_COOKIE)
    if not code_verifier or not nonce:
        logger.warning("Google sign-in cookies missing or expired")
        return sessions.sign_in_error_redirect("sign_in_failed")

    try:
        claims = await google_sign_in.exchange_code(
            code=code, code_verifier=code_verifier, nonce=nonce
        )
    except GoogleSignInError as exc:
        logger.warning("Google sign-in failed: %s", exc)
        return sessions.sign_in_error_redirect("sign_in_failed")
    if not may_sign_in(claims.email):
        return sessions.sign_in_error_redirect(EMAIL_NOT_ALLOWED)

    # One sign-in, one transaction: the User, their Google identity and the
    # Session commit together, or not at all.
    user = await google_identities_service.resolve_user(db, claims)
    result = await sessions.start(
        db,
        user=user,
        sign_in_method="google",
        client=sessions.ClientInfo.from_request(request),
    )
    if isinstance(result, sessions.SessionRefusal):
        # A refused sign-in keeps nothing: no new Google identity, no profile fill.
        await db.rollback()
        return result.as_sign_in_redirect()
    await db.commit()
    return result.as_callback_redirect("/oauth/google/callback")


def _state_flow(state: str) -> Optional[str]:
    try:
        payload = decode_payload(state)
    except (json.JSONDecodeError, ValueError, binascii.Error):
        return None
    return payload.get("flow") if isinstance(payload, dict) else None


def _google_cookie_attributes(key: str) -> dict[str, Any]:
    """A Google sign-in cookie's attributes, the same where it is set and where it is cleared."""
    return {
        "key": key,
        "path": "/",
        "httponly": True,
        "secure": settings.serves_https(),
        "samesite": "lax",
    }


def _delete_google_cookies(response: RedirectResponse) -> None:
    # The state, nonce and PKCE verifier are single-use, whatever the outcome.
    for key in _GOOGLE_COOKIES:
        response.delete_cookie(**_google_cookie_attributes(key))


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
    An email the Sign-up allowlist refuses raises `EmailNotAllowedError` and sends nothing.
    """
    if not may_sign_in(email):
        raise EmailNotAllowedError()
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
                link_url=f"{settings.api_url()}/login/magic-link?token={issued.token}",
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
    `invalid_magic_link`, `account_suspended`, `email_not_allowed` or `sign_in_failed`. An
    unexpected exception is reported and rolled back, so a failure halfway leaves no User behind.
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
    if not may_sign_in(redeemed.email):
        # Commit so the single-use Magic link stays consumed, before any User is created.
        await db.commit()
        return sessions.sign_in_error_redirect(EMAIL_NOT_ALLOWED)

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
    target = "https://mail.google.com/mail/u/0/#inbox"
    # Without SMTP no email is sent, so there is no sender to filter on.
    if settings.EMAIL_FROM:
        query = f"from:{settings.EMAIL_FROM}"
        target = f"https://mail.google.com/mail/u/0/#search/{quote(query, safe='')}"
    return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)


async def refresh_token(request: Request, db: AsyncSession) -> JSONResponse:
    """
    Rotate the Session of the presented refresh cookie, or answer 401 on any refusal.
    """
    result = await sessions.rotate(
        db,
        refresh_cookie=sessions.read_refresh_cookie(request),
        client=sessions.ClientInfo.from_request(request),
    )
    # Commit refusals too: a reused refresh token revokes its Session, and that
    # must persist even though this request answers 401.
    await db.commit()
    return result.as_json_response()


async def logout(request: Request, db: AsyncSession) -> JSONResponse:
    """
    End only the Session of the presented refresh cookie. Signing out always succeeds;
    a failure while revoking is unexpected and reaches the global handler.
    """
    await sessions.end(db, refresh_cookie=sessions.read_refresh_cookie(request))
    await db.commit()
    return sessions.ended_session_response()


MAX_API_KEYS = 10


def _api_key_response(api_key: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=api_key.id,
        name=api_key.name,
        prefix=api_key.prefix,
        created_at=as_utc(api_key.created_at),
        last_used_at=as_utc(api_key.last_used_at) if api_key.last_used_at else None,
    )


def _claude_command(secret: str) -> str:
    """The `claude mcp add` line that connects Claude Code to this Instance's MCP endpoint."""
    server_name = re.sub(r"[^a-z0-9]+", "-", settings.APP_NAME.lower()).strip("-") or "pumpkit"
    return (
        f"claude mcp add --transport http {server_name} {settings.api_url()}/mcp"
        f' --header "Authorization: Bearer {secret}"'
    )


async def create_api_key(
    db: AsyncSession, user: User, name: str, now: datetime
) -> ApiKeyCreatedResponse:
    if await api_keys.count_unrevoked_api_keys(db, user_id=user.id) >= MAX_API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"You already have {MAX_API_KEYS} API keys, the most you can hold. "
                "Revoke one to create another."
            ),
        )
    api_key, secret = await api_keys.create_api_key(db, user_id=user.id, name=name, now=now)
    await db.commit()
    return ApiKeyCreatedResponse(
        api_key=_api_key_response(api_key), secret=secret, claude_command=_claude_command(secret)
    )


async def list_api_keys(db: AsyncSession, user: User) -> ApiKeysListResponse:
    keys = await api_keys.list_unrevoked_api_keys(db, user_id=user.id)
    return ApiKeysListResponse(data=[_api_key_response(api_key) for api_key in keys])


async def revoke_api_key(db: AsyncSession, user: User, api_key_id: str, now: datetime) -> None:
    """Revoke one of the User's keys; another User's key and a revoked one both read as a 404."""
    api_key = await api_keys.get_unrevoked_api_key(db, user_id=user.id, api_key_id=api_key_id)
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That API key doesn't exist or was already revoked.",
        )
    await api_keys.revoke_api_key(db, api_key, now=now)
    await db.commit()


async def authenticate_api_key(db: AsyncSession, secret: str, now: datetime) -> Optional[User]:
    """
    The User an API key acts for, recording that the key was used; None for an unknown or
    revoked key, or a User who is Suspended now, as `get_current_user` refuses one.
    """
    api_key = await api_keys.get_unrevoked_api_key_by_secret(db, secret=secret)
    if api_key is None:
        return None
    user = await user_service.get_user_by_id(db=db, user_id=api_key.user_id)
    if user is None or not sessions.may_hold_session(user):
        return None
    await api_keys.record_use(db, api_key, now=now)
    await db.commit()
    return user
