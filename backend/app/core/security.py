import base64
import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.logger import logger

TokenType = Literal["access", "refresh"]


# Plain bearer scheme: access tokens come from magic-link and OAuth sign-in, not a password grant.
# auto_error=False so we raise the 401 and Bearer challenge ourselves, whatever FastAPI's default.
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_bearer_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> str:
    """FastAPI dependency: the raw bearer token, or 401 if it is missing or malformed."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


_fernet = Fernet(settings.FERNET_ENCRYPTION_KEY.encode())


def encrypt(s: str) -> str:
    if not s:
        return s
    return _fernet.encrypt(s.encode()).decode()


def decrypt(s: str) -> str:
    """Return "" on an invalid token rather than raise, so bad ciphertext never fails a request."""
    if not s:
        return s
    try:
        return _fernet.decrypt(s.encode()).decode()
    except InvalidToken:
        logger.exception(
            "Unexpected error during decryption of string %s. An empty string will be returned.", s
        )
        return ""


def encrypt_bytes(data: bytes) -> bytes:
    if not data:
        return data
    return _fernet.encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    """Binary counterpart of ``decrypt``, with the same return-empty-on-invalid-token contract."""
    if not token:
        return token
    try:
        return _fernet.decrypt(token)
    except InvalidToken:
        logger.exception("Decryption failed for binary blob")
        return b""


def generate_token(num_bytes: Optional[int] = 64) -> str:
    return secrets.token_urlsafe(num_bytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)


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

    # Standard JWT claims for security
    to_encode.update(
        {
            "exp": now + expires_in,  # Expiration time
            "iat": now,  # Issued at
            "nbf": now,  # Not before
            "iss": settings.JWT_ISSUER,  # Issuer
            "aud": settings.JWT_AUDIENCE,  # Audience
            "jti": str(uuid.uuid4()),  # JWT ID (unique identifier)
            "typ": token_type,  # Token type
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


def encode_payload(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(data).decode("utf-8")
    return encoded.rstrip("=")


def decode_payload(value: str) -> dict[str, Any]:
    padding = 4 - (len(value) % 4)
    if padding and padding != 4:
        value += "=" * padding
    decoded = base64.urlsafe_b64decode(value.encode("utf-8"))
    result = json.loads(decoded.decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("State payload must be a JSON object")
    return result
