from typing import Final

from google.auth.transport import requests as google_requests

# Google OAuth parameters
GOOGLE_AUTHORIZATION_ENDPOINT: Final[str] = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT: Final[str] = "https://oauth2.googleapis.com/token"
GOOGLE_NONCE_COOKIE: Final[str] = "google_oauth_nonce"
GOOGLE_CODE_VERIFIER_COOKIE: Final[str] = "google_oauth_code_verifier"
GOOGLE_OAUTH_LOGIN_SCOPES: Final[list[str]] = [
    "openid",
    "email",
    "profile",
]
GOOGLE_LOGIN_STATE_COOKIE: Final[str] = "google_oauth_login_state"

# Google OAuth JWKS request
GOOGLE_JWKS_REQUEST = google_requests.Request()
