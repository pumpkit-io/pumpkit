import base64
import binascii
import hashlib
import json
from typing import Optional
from urllib.parse import urlencode

from fastapi import Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.google_identities as google_identities_service
import app.api.services.sessions as sessions
from app.api.configs.google import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GOOGLE_CODE_VERIFIER_COOKIE,
    GOOGLE_LOGIN_STATE_COOKIE,
    GOOGLE_NONCE_COOKIE,
    GOOGLE_OAUTH_LOGIN_SCOPES,
)
from app.core.config import settings
from app.core.exceptions import report_unexpected_exception
from app.core.google_sign_in import GoogleSignIn, GoogleSignInError
from app.core.logger import logger
from app.core.security import (
    decode_payload,
    encode_payload,
    generate_token,
)


async def login_google() -> JSONResponse:
    """
    Start Google OAuth login by generating and returning the authorization URL.
    The returned response includes cookies with PKCE and CSRF protection state.
    """
    # Generate the state and nonce
    state_payload = {
        "flow": "login",
        "nonce": generate_token(num_bytes=settings.GOOGLE_NONCE_TOKEN_NUM_BYTES),
    }
    state = encode_payload(state_payload)
    nonce = generate_token(num_bytes=settings.GOOGLE_NONCE_TOKEN_NUM_BYTES)
    code_verifier = generate_token(num_bytes=settings.GOOGLE_CODE_VERIFIER_TOKEN_NUM_BYTES)

    # Generate the code challenge
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )

    # Craft the query parameters for the authorization URL
    query_params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(GOOGLE_OAUTH_LOGIN_SCOPES),
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
    }

    # Create the response with the authorization URL
    authorization_url = f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode(query_params)}"

    response = JSONResponse(content={"url": authorization_url})

    # Set the cookies
    cookie_kwargs = {
        "max_age": settings.GOOGLE_COOKIE_MAX_AGE_SECONDS,
        "secure": settings.is_env_production(),
        "httponly": True,
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(key=GOOGLE_LOGIN_STATE_COOKIE, value=state, **cookie_kwargs)
    response.set_cookie(key=GOOGLE_NONCE_COOKIE, value=nonce, **cookie_kwargs)
    response.set_cookie(key=GOOGLE_CODE_VERIFIER_COOKIE, value=code_verifier, **cookie_kwargs)

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
    Finish Google sign-in where Google sends the browser back. It always ends on
    a redirect: the frontend callback with a new Session, or the sign-in page
    with `sign_in_failed` or `account_suspended`. An unexpected exception is
    reported like the global handler would, and the sign-in is rolled back, so
    a failure halfway leaves no User or Google identity behind.
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
        response = _sign_in_failed_redirect()
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
        return _sign_in_failed_redirect()
    if not code or not state:
        logger.warning("Google sign-in callback without a code or state")
        return _sign_in_failed_redirect()

    # The state must be the one this browser was given, for the sign-in flow (CSRF).
    if state != request.cookies.get(GOOGLE_LOGIN_STATE_COOKIE) or _state_flow(state) != "login":
        logger.warning("Google sign-in state mismatch")
        return _sign_in_failed_redirect()

    code_verifier = request.cookies.get(GOOGLE_CODE_VERIFIER_COOKIE)
    nonce = request.cookies.get(GOOGLE_NONCE_COOKIE)
    if not code_verifier or not nonce:
        logger.warning("Google sign-in cookies missing or expired")
        return _sign_in_failed_redirect()

    try:
        claims = await google_sign_in.exchange_code(
            code=code, code_verifier=code_verifier, nonce=nonce
        )
    except GoogleSignInError as exc:
        logger.warning("Google sign-in failed: %s", exc)
        return _sign_in_failed_redirect()

    # One sign-in, one transaction: the User, their Google identity and the
    # Session commit together.
    user = await google_identities_service.resolve_user(db, claims)
    result = await sessions.start(
        db,
        user=user,
        sign_in_method="google",
        client=sessions.ClientInfo.from_request(request),
    )
    await db.commit()
    if isinstance(result, sessions.SessionRefusal):
        return result.as_sign_in_redirect()
    return result.as_callback_redirect("/oauth/google/callback")


def _state_flow(state: str) -> Optional[str]:
    try:
        payload = decode_payload(state)
    except (json.JSONDecodeError, ValueError, binascii.Error):
        return None
    return payload.get("flow") if isinstance(payload, dict) else None


def _sign_in_failed_redirect() -> RedirectResponse:
    return RedirectResponse(
        url=f"{settings.FRONTEND_URL}/login?error=sign_in_failed",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _delete_google_cookies(response: RedirectResponse) -> None:
    # The state, nonce and PKCE verifier are single-use, whatever the outcome.
    response.delete_cookie(key=GOOGLE_LOGIN_STATE_COOKIE, path="/")
    response.delete_cookie(key=GOOGLE_NONCE_COOKIE, path="/")
    response.delete_cookie(key=GOOGLE_CODE_VERIFIER_COOKIE, path="/")
