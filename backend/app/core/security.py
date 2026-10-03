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
from fastapi import status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext

from app.core.config import settings
from app.core.logger import logger

TokenType = Literal["access", "refresh"]


# FastAPI dependency to extract the access token from the Authorization header "Bearer <token>"
# The tokenUrl is just for OpenAPI documentation - it doesn't affect the actual token extraction.
# The tokenUrl should point to the endpoint that returns the access token in its content: {"access_token": "<token>", ...}
oauth2_scheme: OAuth2PasswordBearer = OAuth2PasswordBearer(tokenUrl="login")

# Password hashing helper
_pwd_context: CryptContext = CryptContext(schemes=["argon2"], deprecated="auto")

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


####################
# PASSWORD HASHING #
####################


def hash_password(plain_password: str) -> str:
    """
    Hash a plain-text password.

    Argon2 is preferable over SHA-256 for hashing user passwords. User passwords often have
    low entropy, making them vulnerable to brute force attacks. SHA-256 is built to be lightning fast,
    so hackers could check billions of password hashes per second. Argon2 instead is intentionally slow
    and memory-intensive, making it more difficult to crack via brute force attacks.
    """
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify that, after being hashed, the given plain password matches the given hashed password
    """
    return _pwd_context.verify(plain_password, hashed_password)


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
    except jwt.JWTError:
        return None


#############################
# REQUEST RESPONSE CREATION #
#############################


def create_auth_response(access_token: str, refresh_token: str) -> JSONResponse:
    """
    Create a JSON response with the provided access token, the access token's expiration datetime, and
    an HTTP-only cookie containing the refresh token.
    """
    # Access token expiration datetime
    expires_at: datetime = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )

    # Create response with access token information
    response = JSONResponse(
        content={
            "access_token": access_token,  # Access token is short-lived - can be stored in memory
            "token_type": "Bearer",
            "expires_at": expires_at.isoformat(),
        },
        status_code=status.HTTP_200_OK,
        headers={
            # Required by OAuth for responses containing credentials (cookies included)
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )

    # Use "__Host-" prefix in production for enhanced security.
    # A cookie whose name starts with "__Host-" is accepted only if it:
    # 1. is sent over HTTPS (like in production)
    # 2. doesn't have the domain attribute
    # 3. has the path="/" attribute
    # If any of the above conditions are not met, the cookie is rejected - better security.
    cookie_name = "__Host-refresh_token" if settings.is_env_production() else "refresh_token"

    # Set refresh token as HTTP-only cookie to enhance security
    response.set_cookie(
        key=cookie_name,
        value=refresh_token,
        max_age=settings.COOKIE_MAX_AGE_SECONDS,
        httponly=True,  # Mitigates JS theft (XSS) attacks
        secure=settings.is_env_production(),
        samesite="lax",
        path="/",
        # Cannot set domain if using "__Host-" prefix
    )

    return response


def create_redirect_response(redirect_url: str, refresh_token: str) -> RedirectResponse:
    """
    Create a redirect response with the provided redirect URL and an HTTP-only cookie containing the refresh token.
    """
    response = RedirectResponse(
        url=redirect_url,
        status_code=status.HTTP_303_SEE_OTHER,  # PRG pattern
        headers={
            # Required by OAuth for responses containing credentials (cookies included)
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )

    # Use "__Host-" prefix in production for enhanced security.
    cookie_name = "__Host-refresh_token" if settings.is_env_production() else "refresh_token"

    # Set refresh token as HTTP-only cookie to enhance security
    response.set_cookie(
        key=cookie_name,
        value=refresh_token,
        max_age=settings.COOKIE_MAX_AGE_SECONDS,
        httponly=True,  # Mitigates JS theft (XSS) attacks
        secure=settings.is_env_production(),
        samesite="lax",
        path="/",
        # Cannot set domain if using "__Host-" prefix
    )

    return response


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
