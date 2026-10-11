"""Session JWTs: the short-lived access token and the refresh token a Session rotates."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import jwt

from pumpkit.core.config import settings

TokenType = Literal["access", "refresh"]


def create_access_token(data: dict) -> str:
    return _create_auth_token(
        data,
        expires_in=timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        token_type="access",
    )


def create_refresh_token(data: dict) -> str:
    return _create_auth_token(
        data,
        expires_in=timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        token_type="refresh",
    )


def _create_auth_token(data: dict, expires_in: timedelta, token_type: TokenType) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)

    to_encode.update(
        {
            "exp": now + expires_in,
            "iat": now,
            "nbf": now,
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
            "jti": str(uuid.uuid4()),
            "typ": token_type,
        }
    )

    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def verify_access_token(token: str) -> Optional[dict]:
    return _verify_auth_token(
        token=token,
        expected_type="access",
    )


def verify_refresh_token(token: str) -> Optional[dict]:
    return _verify_auth_token(
        token=token,
        expected_type="refresh",
    )


def _verify_auth_token(token: str, expected_type: TokenType) -> Optional[dict]:
    try:
        # An explicit algorithm list prevents algorithm-confusion attacks.
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={
                "require": ["exp", "iat", "nbf", "iss", "aud", "jti", "typ"],
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
                "verify_iss": True,
                "verify_aud": True,
            },
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
        )

        if payload.get("typ") != expected_type:
            return None

        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
