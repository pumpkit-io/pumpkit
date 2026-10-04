import base64
import binascii
import hashlib
import json
from typing import Any, Optional
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.google_identities as google_identities_service
import app.api.services.sessions as sessions
from app.api.configs.google import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GOOGLE_CODE_VERIFIER_COOKIE,
    GOOGLE_NONCE_COOKIE,
    GOOGLE_SIGN_IN_SCOPES,
    GOOGLE_SIGN_IN_STATE_COOKIE,
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

# The `flow` the state carries, so a state minted for another Google flow can't sign in.
_SIGN_IN_FLOW = "sign_in"

# The single-use state, nonce and PKCE verifier cookies of a Google sign-in.
_GOOGLE_COOKIES = (GOOGLE_SIGN_IN_STATE_COOKIE, GOOGLE_NONCE_COOKIE, GOOGLE_CODE_VERIFIER_COOKIE)


async def start_google_sign_in() -> JSONResponse:
    """
    Start Google sign-in by generating and returning the authorization URL.
    The returned response includes cookies with PKCE and CSRF protection state.
    """
    # Generate the state and nonce
    state_payload = {
        "flow": _SIGN_IN_FLOW,
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
        "scope": " ".join(GOOGLE_SIGN_IN_SCOPES),
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
        "secure": settings.is_env_production(),
        "samesite": "lax",
    }


def _delete_google_cookies(response: RedirectResponse) -> None:
    # The state, nonce and PKCE verifier are single-use, whatever the outcome.
    for key in _GOOGLE_COOKIES:
        response.delete_cookie(**_google_cookie_attributes(key))
