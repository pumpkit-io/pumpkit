from typing import Final

from google.auth.transport import requests as google_requests

GOOGLE_AUTHORIZATION_ENDPOINT: Final[str] = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT: Final[str] = "https://oauth2.googleapis.com/token"
GOOGLE_NONCE_COOKIE: Final[str] = "google_oauth_nonce"
GOOGLE_CODE_VERIFIER_COOKIE: Final[str] = "google_oauth_code_verifier"
GOOGLE_SIGN_IN_SCOPES: Final[list[str]] = [
    "openid",
    "email",
    "profile",
]
GOOGLE_SIGN_IN_STATE_COOKIE: Final[str] = "google_oauth_sign_in_state"

# Transport for fetching Google's JWKS when verifying ID tokens.
GOOGLE_JWKS_REQUEST = google_requests.Request()
