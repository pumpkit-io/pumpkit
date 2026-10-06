"""The `GoogleSignIn` port: turns Google's authorization code into verified identity claims.

Mediators reach Google only through `get_google_sign_in`; tests override it with `FakeGoogleSignIn`.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Optional, Protocol

import requests
from fastapi import status
from google.auth.exceptions import GoogleAuthError
from google.oauth2 import id_token
from starlette.concurrency import run_in_threadpool

from app.api.configs.google import GOOGLE_JWKS_REQUEST, GOOGLE_TOKEN_ENDPOINT
from app.core.config import settings


class GoogleSignInError(Exception):
    """Google did not prove who the User is: the exchange failed or the claims are unusable."""


@dataclass(frozen=True)
class GoogleClaims:
    """Who Google says signed in: the account's subject, its verified email and name hints."""

    subject: str
    email: str
    given_name: Optional[str] = None
    family_name: Optional[str] = None
    name: Optional[str] = None
    # The verified ID-token payload, kept on the Google identity as its profile.
    profile: dict[str, Any] = field(default_factory=dict)


class GoogleSignIn(Protocol):
    async def exchange_code(self, *, code: str, code_verifier: str, nonce: str) -> GoogleClaims:
        """Exchange the authorization code for verified claims, or raise `GoogleSignInError`."""
        ...


class GoogleOAuthSignIn:
    """Exchanges the code at Google's token endpoint and verifies the ID token, off the event loop."""

    async def exchange_code(self, *, code: str, code_verifier: str, nonce: str) -> GoogleClaims:
        return await run_in_threadpool(
            self._exchange_code, code=code, code_verifier=code_verifier, nonce=nonce
        )

    def _exchange_code(self, *, code: str, code_verifier: str, nonce: str) -> GoogleClaims:
        try:
            token_response = requests.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_CLIENT_ID,
                    "client_secret": settings.GOOGLE_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                },
                timeout=settings.GOOGLE_TOKEN_ENDPOINT_TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            raise GoogleSignInError("Google token endpoint unreachable") from error

        # The token endpoint's body carries tokens: log only the status.
        if token_response.status_code != status.HTTP_200_OK:
            raise GoogleSignInError(f"Google token endpoint returned {token_response.status_code}")
        try:
            token_data = token_response.json()
        except ValueError as error:
            raise GoogleSignInError("Google token endpoint returned invalid JSON") from error

        id_token_value = token_data.get("id_token") if isinstance(token_data, dict) else None
        if not id_token_value:
            raise GoogleSignInError("Google token response has no ID token")

        try:
            id_info = id_token.verify_oauth2_token(
                id_token_value, GOOGLE_JWKS_REQUEST, settings.GOOGLE_CLIENT_ID
            )
        except (ValueError, GoogleAuthError) as error:
            raise GoogleSignInError("Google ID token failed verification") from error

        if id_info.get("nonce") != nonce:
            raise GoogleSignInError("Google ID token nonce mismatch")
        email = id_info.get("email")
        if not email or not id_info.get("email_verified", False):
            raise GoogleSignInError("Google account email missing or unverified")
        subject = id_info.get("sub")
        if not subject:
            raise GoogleSignInError("Google ID token has no subject")

        return GoogleClaims(
            subject=subject,
            email=email,
            given_name=id_info.get("given_name"),
            family_name=id_info.get("family_name"),
            name=id_info.get("name"),
            profile=dict(id_info),
        )


@dataclass
class FakeGoogleSignIn:
    """Answers every exchange with `claims`. Set `fail = True` to make it raise `GoogleSignInError`."""

    claims: Optional[GoogleClaims] = None
    fail: bool = False

    async def exchange_code(self, *, code: str, code_verifier: str, nonce: str) -> GoogleClaims:
        if self.fail or self.claims is None:
            raise GoogleSignInError("Fake Google sign-in is set to fail")
        return self.claims


@lru_cache
def get_google_sign_in() -> GoogleSignIn:
    """FastAPI dependency for the `GoogleSignIn` port."""
    return GoogleOAuthSignIn()
