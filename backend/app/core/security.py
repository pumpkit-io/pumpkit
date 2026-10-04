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


# Extracts the access token from an "Authorization: Bearer <token>" header. Access tokens are
# issued by the magic-link and OAuth sign-in flows, so this is a plain bearer scheme rather than
# an OAuth2 password grant. auto_error=False lets us raise the 401 + "WWW-Authenticate: Bearer"
# challenge ourselves, independent of the installed FastAPI version's HTTPBearer default.
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_bearer_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> str:
    """
    FastAPI dependency returning the raw bearer token, or raising 401 if it is missing or malformed.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


# Data encryption helper
_fernet = Fernet(settings.FERNET_ENCRYPTION_KEY.encode())


#############################
# ENCRYPTION AND DECRYPTION #
#############################


def encrypt(s: str) -> str:
    """
    Encrypt the given string.
    """
    if not s:
        return s
    return _fernet.encrypt(s.encode()).decode()


def decrypt(s: str) -> str:
    """
    Decrypt the given string.
    """
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
    """Encrypt the given binary blob with the same Fernet key used for text fields.

    Returns the raw Fernet token bytes. Empty input passes through unchanged so
    callers don't have to special-case ``b""``.
    """
    if not data:
        return data
    return _fernet.encrypt(data)


def decrypt_bytes(token: bytes) -> bytes:
    """Decrypt a Fernet token produced by ``encrypt_bytes``.

    Mirrors the loud-failure-becomes-soft-failure contract of ``decrypt``: on
    ``InvalidToken`` we log and return ``b""`` rather than crashing the request.
    """
    if not token:
        return token
    try:
        return _fernet.decrypt(token)
    except InvalidToken:
        logger.exception("Decryption failed for binary blob")
        return b""


#######################################
# RANDOM TOKEN GENERATION AND HASHING #
#######################################


def generate_token(num_bytes: Optional[int] = 64) -> str:
    """
    Generate a secure, random token of the given number of bytes.
    """
    return secrets.token_urlsafe(num_bytes)


def hash_token(token: str) -> str:
    """
    Hash the given token for secure storage.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token(token: str, token_hash: str) -> bool:
    """
    Verify that the given token matches its given hash.
    """
    return hmac.compare_digest(hash_token(token), token_hash)


#################################
# JWT CREATION AND VERIFICATION #
#################################


def create_access_token(data: dict) -> str:
    """
    Create an access token whose payload contains the given data.
    """
    return _create_auth_token(
        data,
        expires_in=timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        token_type="access",
    )


def create_refresh_token(data: dict) -> str:
    """
    Create a refresh token whose payload contains the given data.
    """
    return _create_auth_token(
        data,
        expires_in=timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        token_type="refresh",
    )


def _create_auth_token(data: dict, expires_in: timedelta, token_type: TokenType) -> str:
    """
    Create a JWT token of the given type, expires in the given amount of time, and whose payload contains the given data.
    """
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
    """
    Verify and decode the given access token. Returns the payload if the token is valid, otherwise returns None.
    """
    return _verify_auth_token(
        token=token,
        expected_type="access",
    )


def verify_refresh_token(token: str) -> Optional[dict]:
    """
    Verify and decode the given refresh token. Returns the payload if the token is valid, otherwise returns None.
    """
    return _verify_auth_token(
        token=token,
        expected_type="refresh",
    )


def _verify_auth_token(token: str, expected_type: TokenType) -> Optional[dict]:
    """
    Verify and decode the given JWT token with proper claim validation. Returns the payload if the token is valid, otherwise returns None.
    """
    try:
        # Decode with explicit algorithm validation to prevent algorithm confusion attacks
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            # Validate standard claims
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

        # Validate token type
        if payload.get("typ") != expected_type:
            return None

        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


#################################
# PAYLOAD ENCODING AND DECODING #
#################################


def encode_payload(payload: dict[str, Any]) -> str:
    """
    Encode a dict-like payload as a URL-safe base64 string without padding.
    """
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(data).decode("utf-8")
    return encoded.rstrip("=")


def decode_payload(value: str) -> dict[str, Any]:
    """
    Decode a base64-encoded dict-like payload.
    """
    padding = 4 - (len(value) % 4)
    if padding and padding != 4:
        value += "=" * padding
    decoded = base64.urlsafe_b64decode(value.encode("utf-8"))
    result = json.loads(decoded.decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError("State payload must be a JSON object")
    return result
