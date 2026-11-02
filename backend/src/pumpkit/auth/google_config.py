from dataclasses import dataclass
from typing import Final

from google.auth.transport import requests as google_requests

from pumpkit.core.config import settings

GOOGLE_NONCE_COOKIE: Final[str] = "google_oauth_nonce"
GOOGLE_CODE_VERIFIER_COOKIE: Final[str] = "google_oauth_code_verifier"
GOOGLE_SIGN_IN_SCOPES: Final[list[str]] = [
    "openid",
    "email",
    "profile",
]
GOOGLE_SIGN_IN_STATE_COOKIE: Final[str] = "google_oauth_sign_in_state"

# Transport for fetching Google's certs when verifying ID tokens.
GOOGLE_JWKS_REQUEST = google_requests.Request()


@dataclass(frozen=True)
class GoogleEndpoints:
    """Where Google sign-in sends the browser, exchanges codes and fetches certs, and whom ID tokens must name as issuer."""

    authorization: str
    token: str
    certs: str
    issuers: tuple[str, ...]


_GOOGLE: Final = GoogleEndpoints(
    authorization="https://accounts.google.com/o/oauth2/v2/auth",
    token="https://oauth2.googleapis.com/token",
    certs="https://www.googleapis.com/oauth2/v1/certs",
    issuers=("accounts.google.com", "https://accounts.google.com"),
)


def google_endpoints() -> GoogleEndpoints:
    """Google's own endpoints, or the Emulator's that `GOOGLE_ISSUER` and `GOOGLE_API_URL` name."""
    if not settings.GOOGLE_ISSUER or not settings.GOOGLE_API_URL:
        return _GOOGLE
    return GoogleEndpoints(
        authorization=f"{settings.GOOGLE_ISSUER}/o/oauth2/v2/auth",
        # The discovery document advertises the browser-facing route, which a container can't reach.
        token=f"{settings.GOOGLE_API_URL}/oauth2/token",
        certs=f"{settings.GOOGLE_API_URL}/oauth2/v3/certs",
        issuers=(settings.GOOGLE_ISSUER,),
    )
