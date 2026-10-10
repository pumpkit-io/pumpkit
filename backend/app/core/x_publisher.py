"""
The `XPublisher` port: the official X API, used on a User's behalf through their X
connection (ADR 0006). Ported from pumpkit-v5's X client, made async and stateless.

It returns plain data and never touches the database: storing and encrypting tokens is
the callers' job. Tokens X refuses for good raise `XReconnectNeededError`; any other
failure is an `XPublisherError` (a 502 with an `error_id`), and missing X app settings an
`XPublisherNotConfiguredError`. Publishing raises one subclass per outcome the caller must
tell apart (ADR 0007): rate limited, not received, outcome unknown, and rejected.

Mediators reach X only through `get_x_publisher`; tests override it with `FakeXPublisher`.
"""

import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Literal, Optional, Protocol
from urllib.parse import urlencode

import httpx

from app.core.config import settings

X_AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
X_TOKEN_URL = "https://api.x.com/2/oauth2/token"
X_REVOKE_URL = "https://api.x.com/2/oauth2/revoke"
X_USERS_ME_URL = "https://api.x.com/2/users/me"
X_TWEETS_URL = "https://api.x.com/2/tweets"
X_SCOPES = "tweet.read tweet.write users.read offline.access"
_TIMEOUT_SECONDS = 30.0
# X's documented access token lifetime, used when a token response leaves out expires_in.
_DEFAULT_EXPIRES_IN_SECONDS = 7200
# X's refusals are shown to the User; this keeps a runaway body readable.
_MAX_DETAIL_CHARS = 300
# OAuth errors no retry fixes: the code or refresh token is spent or revoked, or the app is wrong.
_PERMANENT_TOKEN_ERRORS = {"invalid_grant", "invalid_client"}

TokenTypeHint = Literal["access_token", "refresh_token"]


class XPublisherError(Exception):
    """A call to X failed: network, HTTP, or a response that can't be read."""


class XPublisherNotConfiguredError(XPublisherError):
    """Raised when X is called without the X app settings."""

    def __init__(self) -> None:
        super().__init__(
            "X_CLIENT_ID, X_CLIENT_SECRET and X_REDIRECT_URI must be set in backend/.env "
            "to connect X accounts."
        )


class XReconnectNeededError(XPublisherError):
    """X refuses these tokens for good: only the User going through X's consent screen again helps."""


class XRateLimitedError(XPublisherError):
    """X answered 429: nothing was published."""


class XNotReceivedError(XPublisherError):
    """The request never reached X (no connection was made), so nothing was published."""


class XOutcomeUnknownError(XPublisherError):
    """X may have published the post: it timed out, failed with a 5xx, or gave no post id."""


class XPostRejectedError(XPublisherError):
    """X refused the post; `message` is X's own words, fit to show the User."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"X refused the post with HTTP {status_code}")
        self.message = message


@dataclass(frozen=True)
class XTokens:
    access_token: str
    refresh_token: str
    expires_at: datetime
    scope: str


@dataclass(frozen=True)
class XAccount:
    """The X account a token acts for."""

    user_id: str
    handle: str
    # X's `subscription_type` ("None", "Basic", "Premium", "PremiumPlus"); None when left out.
    subscription_type: Optional[str]


def new_code_verifier() -> str:
    """A fresh PKCE verifier: 86 unreserved characters, inside the 43 to 128 allowed."""
    return secrets.token_urlsafe(64)


def code_challenge_for(verifier: str) -> str:
    """The S256 challenge: base64url of the verifier's SHA-256, without padding, which X rejects."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class XPublisher(Protocol):
    def build_authorize_url(self, *, state: str, code_challenge: str) -> str:
        """Where to send the User's browser for X's consent screen."""
        ...

    async def exchange_code(self, *, code: str, code_verifier: str, now: datetime) -> XTokens:
        """
        The tokens for a code from X's redirect. A grant without a refresh token raises
        `XReconnectNeededError`: it would stop working within two hours.
        """
        ...

    async def refresh(self, *, refresh_token: str, now: datetime) -> XTokens:
        """
        New tokens for a refresh token. X rotates the refresh token: the old one stops
        working, so the caller must store the new one before anything else.
        """
        ...

    async def fetch_account(self, *, access_token: str) -> XAccount:
        """The X account the token acts for; a refused token raises `XReconnectNeededError`."""
        ...

    async def publish(self, *, access_token: str, text: str) -> str:
        """Publish `text` and return X's post id. Never retried: a retry could post it twice."""
        ...

    async def revoke(self, *, token: str, token_type_hint: TokenTypeHint) -> None:
        """Ask X to revoke the token; revoking the refresh token ends the whole grant."""
        ...


class OfficialXPublisher:
    """Calls the X API. The app settings are checked on use, so the app boots without them."""

    def build_authorize_url(self, *, state: str, code_challenge: str) -> str:
        client_id, _, redirect_uri = _x_app()
        query = urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": X_SCOPES,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{X_AUTHORIZE_URL}?{query}"

    async def exchange_code(self, *, code: str, code_verifier: str, now: datetime) -> XTokens:
        _, _, redirect_uri = _x_app()
        body = await _token_call(
            X_TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
        )
        tokens = _tokens_from(body, now=now, previous_refresh_token="")
        if not tokens.refresh_token:
            raise XReconnectNeededError(
                "X returned no refresh token: the authorization is missing the offline.access "
                "scope, so it would stop working within two hours."
            )
        return tokens

    async def refresh(self, *, refresh_token: str, now: datetime) -> XTokens:
        body = await _token_call(
            X_TOKEN_URL, {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )
        return _tokens_from(body, now=now, previous_refresh_token=refresh_token)

    async def fetch_account(self, *, access_token: str) -> XAccount:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.get(
                    X_USERS_ME_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"user.fields": "subscription_type"},
                )
        except httpx.HTTPError as error:
            raise XPublisherError(f"X unreachable: {type(error).__name__}") from error
        if response.status_code == 401:
            raise XReconnectNeededError("X refused the access token reading users/me")
        if response.status_code != 200:
            raise XPublisherError(f"X users/me returned HTTP {response.status_code}")
        body = _json_or_none(response)
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise XPublisherError("X users/me returned a body without data")
        user_id, handle = data.get("id"), data.get("username")
        if not isinstance(user_id, str) or not user_id or not isinstance(handle, str) or not handle:
            raise XPublisherError("X users/me returned no id or username")
        subscription_type = data.get("subscription_type")
        return XAccount(
            user_id=user_id,
            handle=handle,
            subscription_type=subscription_type if isinstance(subscription_type, str) else None,
        )

    async def revoke(self, *, token: str, token_type_hint: TokenTypeHint) -> None:
        await _token_call(X_REVOKE_URL, {"token": token, "token_type_hint": token_type_hint})

    async def publish(self, *, access_token: str, text: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    X_TWEETS_URL,
                    json={"text": text},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as error:
            raise XNotReceivedError(f"X unreachable: {type(error).__name__}") from error
        except httpx.HTTPError as error:
            # The request may have reached X before the connection failed.
            raise XOutcomeUnknownError(f"X didn't answer: {type(error).__name__}") from error

        status = response.status_code
        if status in (200, 201):
            body = _json_or_none(response)
            data = body.get("data") if isinstance(body, dict) else None
            post_id = data.get("id") if isinstance(data, dict) else None
            if not isinstance(post_id, str) or not post_id:
                raise XOutcomeUnknownError(f"X answered HTTP {status} without a post id")
            return post_id
        if status == 401:
            raise XReconnectNeededError("X refused the access token publishing a post")
        if status == 429:
            raise XRateLimitedError("X rate limited publishing a post")
        if status >= 500:
            raise XOutcomeUnknownError(f"X answered HTTP {status} publishing a post")
        raise XPostRejectedError(status, _detail(response))


def _tokens_from(body: dict[str, Any], *, now: datetime, previous_refresh_token: str) -> XTokens:
    """Tokens from a token response; a response without a refresh token keeps the previous one."""
    access_token = body.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise XPublisherError("X's token response carried no access token")
    refresh_token = body.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        refresh_token = previous_refresh_token
    expires_in = body.get("expires_in")
    if not isinstance(expires_in, int):
        expires_in = _DEFAULT_EXPIRES_IN_SECONDS
    scope = body.get("scope")
    return XTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=now + timedelta(seconds=expires_in),
        scope=scope if isinstance(scope, str) else "",
    )


def _detail(response: httpx.Response) -> str:
    """X's own words for a refusal: "duplicate content" says what to do, a status code doesn't."""
    body = _json_or_none(response)
    if isinstance(body, dict):
        # A validation error's own message is more precise than the body's generic detail.
        errors = body.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            message = errors[0].get("message") or errors[0].get("detail")
            if isinstance(message, str) and message:
                return message[:_MAX_DETAIL_CHARS]
        for key in ("detail", "title", "error_description", "error"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value[:_MAX_DETAIL_CHARS]
    text = response.text.strip().replace("\n", " ")
    return text[:_MAX_DETAIL_CHARS] or f"HTTP {response.status_code}"


def _x_app() -> tuple[str, str, str]:
    """The X app's client id, secret and redirect URI, or `XPublisherNotConfiguredError`."""
    client_id, secret, redirect_uri = (
        settings.X_CLIENT_ID,
        settings.X_CLIENT_SECRET,
        settings.X_REDIRECT_URI,
    )
    if not client_id or not secret or not redirect_uri:
        raise XPublisherNotConfiguredError()
    return client_id, secret, redirect_uri


async def _token_call(url: str, data: dict[str, str]) -> dict[str, Any]:
    """
    One form POST to X's OAuth endpoints as a confidential client. Errors carry only the
    status and OAuth error code: the body may echo the tokens.
    """
    client_id, secret, _ = _x_app()
    basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode("ascii")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                url, data=data, headers={"Authorization": f"Basic {basic}"}
            )
    except httpx.HTTPError as error:
        raise XPublisherError(f"X unreachable: {type(error).__name__}") from error

    body = _json_or_none(response)
    if response.status_code != 200:
        error_code = body.get("error") if isinstance(body, dict) else None
        message = f"X's OAuth endpoint returned HTTP {response.status_code} ({error_code})"
        if error_code in _PERMANENT_TOKEN_ERRORS:
            raise XReconnectNeededError(message)
        # invalid_request is OAuth's generic "malformed": a proxy or clock hiccup can cause it too.
        raise XPublisherError(message)
    if not isinstance(body, dict):
        raise XPublisherError("X's OAuth endpoint returned a body that is not a JSON object")
    return body


def _json_or_none(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


@dataclass
class FakeXPublisher:
    """
    X in memory. Every code exchange and refresh issues tokens `access-<id>-<n>` and
    `refresh-<id>-<n>` for `account`, n counting issues, valid for two hours; the authorize
    URL carries its query like X's. Records `exchanges` (code, verifier), `refreshes`
    (refresh tokens sent), `published` (access token, text) and `revoked` tokens. Set
    `fail_exchange`, `fail_refresh`, `fail_fetch_account` or `fail_publish` to an error to
    raise it, `fail_revoke` or `not_configured` to raise.
    """

    account: XAccount = field(
        default_factory=lambda: XAccount(user_id="1001", handle="ada", subscription_type="None")
    )
    exchanges: list[tuple[str, str]] = field(default_factory=list)
    refreshes: list[str] = field(default_factory=list)
    published: list[tuple[str, str]] = field(default_factory=list)
    revoked: list[str] = field(default_factory=list)
    fail_exchange: Optional[XPublisherError] = None
    fail_refresh: Optional[XPublisherError] = None
    fail_publish: Optional[XPublisherError] = None
    fail_fetch_account: Optional[XPublisherError] = None
    fail_revoke: bool = False
    not_configured: bool = False
    issued: int = 0

    def build_authorize_url(self, *, state: str, code_challenge: str) -> str:
        if self.not_configured:
            raise XPublisherNotConfiguredError()
        query = urlencode({"state": state, "code_challenge": code_challenge})
        return f"{X_AUTHORIZE_URL}?{query}"

    async def exchange_code(self, *, code: str, code_verifier: str, now: datetime) -> XTokens:
        self.exchanges.append((code, code_verifier))
        if self.fail_exchange is not None:
            raise self.fail_exchange
        return self._issue(now)

    async def refresh(self, *, refresh_token: str, now: datetime) -> XTokens:
        self.refreshes.append(refresh_token)
        if self.fail_refresh is not None:
            raise self.fail_refresh
        return self._issue(now)

    async def fetch_account(self, *, access_token: str) -> XAccount:
        if self.fail_fetch_account is not None:
            raise self.fail_fetch_account
        return self.account

    async def publish(self, *, access_token: str, text: str) -> str:
        self.published.append((access_token, text))
        if self.fail_publish is not None:
            raise self.fail_publish
        return str(1_890_000_000_000_000_000 + len(self.published))

    async def revoke(self, *, token: str, token_type_hint: TokenTypeHint) -> None:
        self.revoked.append(token)
        if self.fail_revoke:
            raise XPublisherError("Fake X publisher is set to fail revoking")

    def _issue(self, now: datetime) -> XTokens:
        self.issued += 1
        return XTokens(
            access_token=f"access-{self.account.user_id}-{self.issued}",
            refresh_token=f"refresh-{self.account.user_id}-{self.issued}",
            expires_at=now + timedelta(seconds=_DEFAULT_EXPIRES_IN_SECONDS),
            scope=X_SCOPES,
        )


@lru_cache
def get_x_publisher() -> XPublisher:
    """FastAPI dependency for the `XPublisher` port."""
    return OfficialXPublisher()
