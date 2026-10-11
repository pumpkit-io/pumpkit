import base64
import hashlib
import hmac
import json
import secrets
from typing import Any, Optional

from cryptography.fernet import Fernet, InvalidToken

from pumpkit.core.config import settings
from pumpkit.core.logging import logger

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
