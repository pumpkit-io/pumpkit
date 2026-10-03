import base64
import binascii
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import requests
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from google.oauth2 import id_token
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.auth_sessions as auth_sessions_service
import app.api.services.third_party_auth as third_party_auth_service
import app.api.services.users as user_service
from app.api.configs.google import (
    GOOGLE_AUTHORIZATION_ENDPOINT,
    GOOGLE_CODE_VERIFIER_COOKIE,
    GOOGLE_JWKS_REQUEST,
    GOOGLE_LOGIN_STATE_COOKIE,
    GOOGLE_NONCE_COOKIE,
    GOOGLE_OAUTH_LOGIN_SCOPES,
    GOOGLE_TOKEN_ENDPOINT,
)
from app.core.config import settings
from app.core.ids import ulid_with_prefix
from app.core.logger import logger
from app.core.security import (
    create_access_token,
    create_redirect_response,
    create_refresh_token,
    decode_payload,
    encode_payload,
    generate_token,
)
from app.db.models import ThirdPartyAuth, User


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
    code: str,
    state: str,
    db: AsyncSession,
    error: Optional[str] = None,
):
    """
    Route Google OAuth callbacks to the appropriate handler based on the recorded flow.
    """

    if error:
        logger.error("Google OAuth returned error: %s", error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google authentication was cancelled. Please try again.",
        )

    # Decode the state
    try:
        state_payload = decode_payload(state)
    except (json.JSONDecodeError, ValueError, binascii.Error):
        logger.exception("Failed to decode Google OAuth state payload")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state. Please try again.",
        )

    # Route the flow to the appropriate OAuth handler based on the state
    flow = state_payload.get("flow")

    login_state_cookie = request.cookies.get(GOOGLE_LOGIN_STATE_COOKIE)

    if flow == "login" and state == login_state_cookie:
        response = await _handle_login_google_flow(
            request=request,
            code=code,
            state=state,
            db=db,
        )
    else:
        logger.error(
            "Unexpected Google OAuth flow and state combination received. flow=%s, state=%s",
            flow,
            state,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state. Please try again.",
        )

    return response


async def _handle_login_google_flow(
    request: Request,
    code: str,
    state: str,
    db: AsyncSession,
):
    """
    Handle the Google OAuth login flow. Validate state and nonce, exchange the authorization code, and
    issue tokens for this application.
    """
    # Validate state
    stored_state = request.cookies.get(GOOGLE_LOGIN_STATE_COOKIE)
    if not stored_state or stored_state != state:
        logger.error("Google OAuth state mismatch detected")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid login state. Please try signing in again.",
        )

    # Validate code verifier
    code_verifier = request.cookies.get(GOOGLE_CODE_VERIFIER_COOKIE)
    if not code_verifier:
        logger.error("Missing Google OAuth code verifier cookie")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Login session expired. Please try signing in again.",
        )

    # Validate nonce
    nonce = request.cookies.get(GOOGLE_NONCE_COOKIE)
    if not nonce:
        logger.error("Missing Google OAuth nonce cookie")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Login session expired. Please try signing in again.",
        )

    # Exchange the authorization code for tokens
    token_payload = {
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
        "code_verifier": code_verifier,
    }

    try:
        token_response = requests.post(
            GOOGLE_TOKEN_ENDPOINT,
            data=token_payload,
            timeout=settings.GOOGLE_TOKEN_ENDPOINT_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.exception("Failed to exchange Google OAuth code: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not complete login with Google. Please try again.",
        )

    if token_response.status_code != status.HTTP_200_OK:
        logger.error(
            "Google token endpoint returned %s: %s",
            token_response.status_code,
            token_response.text,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Login with Google failed. Please try again.",
        )

    # Parse the token response
    try:
        token_data = token_response.json()
    except ValueError as exc:
        logger.exception("Invalid JSON from Google token endpoint: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Login with Google failed. Please try again.",
        )

    # Validate the token response
    id_token_value = token_data.get("id_token")
    access_token_value = token_data.get("access_token")

    if not id_token_value or not access_token_value:
        logger.error("Incomplete token payload received from Google: %s", token_data)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Login with Google failed. Please try again.",
        )

    # Verify the ID token
    try:
        id_info = id_token.verify_oauth2_token(
            id_token_value,
            GOOGLE_JWKS_REQUEST,
            settings.GOOGLE_CLIENT_ID,
        )
    except ValueError as exc:
        logger.exception("Failed to verify Google ID token: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Login with Google failed. Please try again.",
        )

    # Validate the nonce
    if id_info.get("nonce") != nonce:
        logger.error("Google ID token nonce mismatch")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid login state. Please try signing in again.",
        )

    # Validate the email
    email = id_info.get("email")
    email_verified = id_info.get("email_verified", False)
    if not email or not email_verified:
        logger.error(
            "Google account email missing or unverified. email=%s, verified=%s",
            email,
            email_verified,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your Google account email is not verified. Please verify it with Google and try again.",
        )

    # Validate the subject
    subject = id_info.get("sub")
    if not subject:
        logger.error("Missing subject in Google ID token")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Login with Google failed. Please try again.",
        )

    # Locate or create user and third-party auth record
    user = None
    third_party_auth: Optional[
        ThirdPartyAuth
    ] = await third_party_auth_service.get_third_party_auth(
        db=db,
        provider="google",
        subject=subject,
    )

    if third_party_auth:
        # Get the user from the third-party auth record
        user = await user_service.get_user_by_id(db=db, user_id=third_party_auth.user_id)

    if user is None:
        # Get the user from the email
        user = await user_service.get_user_by_email(db=db, email=email)

    if user is None:
        # Since the user does not exist, we need to create it
        user = User(
            id=ulid_with_prefix("user"),
            email=email,
            display_name=id_info.get("name") or email,
            first_name=id_info.get("given_name"),
            last_name=id_info.get("family_name"),
            is_admin=False,
        )
        await user_service.create_user(db=db, user=user)
    else:
        # Since the user exists, we need to update it
        should_commit = False
        if not user.first_name and id_info.get("given_name"):
            user.first_name = id_info.get("given_name")
            should_commit = True
        if not user.last_name and id_info.get("family_name"):
            user.last_name = id_info.get("family_name")
            should_commit = True
        if not user.display_name and id_info.get("name"):
            user.display_name = id_info.get("name")
            should_commit = True
        if should_commit:
            await db.commit()

    if third_party_auth is None:
        # Since the third-party auth record does not exist, we need to create it
        third_party_auth = ThirdPartyAuth(
            id=ulid_with_prefix("third_party_auth"),
            user_id=user.id,
            provider="google",
            subject=subject,
            profile_json=id_info,
        )
        await third_party_auth_service.create_third_party_auth(
            db=db, third_party_auth=third_party_auth
        )
    else:
        # Since the third-party auth record exists, we need to update it
        third_party_auth.profile_json = id_info
        await db.commit()

    # Create the access token
    access_token = create_access_token(
        data={"sub": user.id, "email": user.email},
    )

    # Create and store the refresh token
    refresh_token = create_refresh_token(
        data={"sub": user.id, "email": user.email},
    )

    await auth_sessions_service.create_auth_session(
        db=db,
        user_id=user.id,
        refresh_token=refresh_token,
        auth_method="google",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    # Create the redirect response
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )

    frontend_redirect_params = {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_at": expires_at.isoformat(),
    }
    frontend_redirect_url = (
        f"{settings.FRONTEND_URL}/oauth/google/callback#{urlencode(frontend_redirect_params)}"
    )

    redirect_response = create_redirect_response(
        redirect_url=frontend_redirect_url,
        refresh_token=refresh_token,
    )

    # Delete the cookies
    redirect_response.delete_cookie(key=GOOGLE_LOGIN_STATE_COOKIE, path="/")
    redirect_response.delete_cookie(key=GOOGLE_NONCE_COOKIE, path="/")
    redirect_response.delete_cookie(key=GOOGLE_CODE_VERIFIER_COOKIE, path="/")

    return redirect_response
