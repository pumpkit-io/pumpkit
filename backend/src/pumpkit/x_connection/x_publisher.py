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

import asyncio
import base64
import hashlib
import secrets
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, BinaryIO, Literal, Optional, Protocol
from urllib.parse import urlencode

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    ValidationError,
    field_validator,
)

from pumpkit.core.config import settings
from pumpkit.core.errors import AppError, NotConfiguredError

X_AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
X_TOKEN_URL = "https://api.x.com/2/oauth2/token"
X_REVOKE_URL = "https://api.x.com/2/oauth2/revoke"
X_USERS_ME_URL = "https://api.x.com/2/users/me"
X_TWEETS_URL = "https://api.x.com/2/tweets"
X_MEDIA_UPLOAD_URL = "https://api.x.com/2/media/upload"
X_MEDIA_METADATA_URL = "https://api.x.com/2/media/metadata"
X_MEDIA_SCOPE = "media.write"
# Every scope Pumpkit uses, asked for at once so a User consents only once (ADR 0006).
X_SCOPES = f"tweet.read tweet.write users.read offline.access {X_MEDIA_SCOPE}"
X_SIGN_IN_SCOPES = f"{X_SCOPES} users.email"
_TIMEOUT_SECONDS = 30.0
# Under X's 5 MB cap on an APPEND segment, with room for the multipart framing around it.
MEDIA_CHUNK_BYTES = 4 * 1024 * 1024
# One APPEND's whole time, under the publisher's 3-minute stop grace period: a slow uplink fails
# the upload, which posted nothing, rather than outlasting a stop.
_APPEND_LIMIT_SECONDS = 120.0
# The longest wait between STATUS polls, so each step of an upload stays short.
_MAX_POLL_WAIT_SECONDS = 60.0
# X's documented access token lifetime, used when a token response leaves out expires_in.
_DEFAULT_EXPIRES_IN_SECONDS = 7200
# X's refusals are shown to the User; this keeps a runaway body readable.
_MAX_DETAIL_CHARS = 300
# OAuth errors no retry fixes: the code or refresh token is spent or revoked, or the app is wrong.
_PERMANENT_TOKEN_ERRORS = {"invalid_grant", "invalid_client"}
# X names its 48px photo `..._normal.jpg`; `_200x200` is the same image, sharp at 96px on 2x screens.
_SMALL_PHOTO_SUFFIX = "_normal"
_LARGER_PHOTO_SUFFIX = "_200x200"

TokenTypeHint = Literal["access_token", "refresh_token"]


class XPublisherError(AppError):
    """A call to X failed: network, HTTP, or a response that can't be read."""

    status_code = 502
    public_detail = "X isn't answering right now. Please try again later."
    reported = True


class XPublisherNotConfiguredError(NotConfiguredError, XPublisherError):
    """Raised when X is called without the X app settings."""

    def __init__(self) -> None:
        super().__init__(
            "X_CLIENT_ID and X_CLIENT_SECRET must be set in .env to connect X accounts."
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

    def __init__(self, x_status: int, message: str) -> None:
        super().__init__(f"X refused the post with HTTP {x_status}")
        self.x_status = x_status
        self.message = message


class XMediaUnavailableError(XPublisherError):
    """A media upload failed for a passing reason; no X post was created with it."""


class XMediaRefusedError(XPublisherError):
    """X refused a media upload or failed to process it; `message` is X's own words."""

    def __init__(self, x_status: Optional[int], message: str) -> None:
        super().__init__(f"X refused the media with HTTP {x_status}")
        self.x_status = x_status
        self.message = message


# X's media_category for what the upload is for, which sets its limits and processing.
MediaCategory = Literal["tweet_image", "tweet_gif", "tweet_video"]
# Kept under the publish's own limit per Media, so this cap ends a slow upload with its own error.
_MEDIA_PROCESSING_SECONDS: dict[MediaCategory, float] = {
    "tweet_image": 3 * 60,
    "tweet_gif": 3 * 60,
    "tweet_video": 30 * 60,
}
# Awaited before each call of an upload for the access token to send with it.
TokenForCall = Callable[[], Awaitable[str]]


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
    photo_url: Optional[str] = None
    confirmed_email: Optional[str] = None
    display_name: Optional[str] = None


class _XProfile(BaseModel):
    model_config = ConfigDict(strict=True)

    id: str = Field(pattern=r"^[0-9]+$")
    username: str = Field(pattern=r"^[A-Za-z0-9_]{1,15}$")
    name: Optional[str] = None
    confirmed_email: Optional[EmailStr] = None
    subscription_type: Optional[str] = None
    profile_image_url: Optional[HttpUrl] = None

    @field_validator("id", "username", "name", "subscription_type")
    @classmethod
    def nonempty_text(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("Expected nonempty text")
        return value


def new_code_verifier() -> str:
    """A fresh PKCE verifier: 86 unreserved characters, inside the 43 to 128 allowed."""
    return secrets.token_urlsafe(64)


def code_challenge_for(verifier: str) -> str:
    """The S256 challenge: base64url of the verifier's SHA-256, without padding, which X rejects."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


class XPublisher(Protocol):
    def build_authorize_url(
        self, *, state: str, code_challenge: str, scopes: str = X_SCOPES
    ) -> str:
        """Where to send the User's browser for X's consent screen."""
        ...

    async def exchange_code(
        self, *, code: str, code_verifier: str, now: datetime, required_scopes: str = ""
    ) -> XTokens:
        """Reject missing offline access or required permissions with `XReconnectNeededError`.
        `required_scopes` must match the scopes requested for this authorization."""
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

    async def upload_media(
        self,
        *,
        token_for_call: TokenForCall,
        source: BinaryIO,
        byte_size: int,
        content_type: str,
        category: MediaCategory,
    ) -> str:
        """
        X's media id for `source` once X processed it. A video's upload can take an hour, so
        `token_for_call` is awaited before every call to X, each chunk and STATUS poll included.
        """
        ...

    async def set_alt_text(self, *, access_token: str, media_id: str, alt_text: str) -> None:
        """
        Describe an uploaded image or GIF for screen readers, before the X post that carries it.
        Failures raise as `upload_media`'s do, and it too may be tried again.
        """
        ...

    async def publish(
        self,
        *,
        access_token: str,
        text: str,
        community_id: Optional[str] = None,
        share_with_followers: bool = False,
        reply_to: Optional[str] = None,
        media_ids: Sequence[str] = (),
    ) -> str:
        """
        X's post id for `text` with `media_ids`, on the profile, in the Community `community_id`,
        or as a reply to `reply_to`. Never retried: a retry could post it twice. A reply lands in
        its parent's Community, so it goes without `community_id` (confirmed live, Oct 2026).
        """
        ...

    async def revoke(self, *, token: str, token_type_hint: TokenTypeHint) -> None:
        """Ask X to revoke the token; revoking the refresh token ends the whole grant."""
        ...


class OfficialXPublisher:
    """Calls the X API. The app settings are checked on use, so the app boots without them."""

    def build_authorize_url(
        self, *, state: str, code_challenge: str, scopes: str = X_SCOPES
    ) -> str:
        client_id, _, redirect_uri = _x_app()
        query = urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": scopes,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{X_AUTHORIZE_URL}?{query}"

    async def exchange_code(
        self, *, code: str, code_verifier: str, now: datetime, required_scopes: str = ""
    ) -> XTokens:
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
        tokens = _tokens_from(
            body, now=now, previous_refresh_token="", requested_scopes=required_scopes
        )
        if not tokens.refresh_token:
            raise XReconnectNeededError(
                "X returned no refresh token: the authorization is missing the offline.access "
                "scope, so it would stop working within two hours."
            )
        return _require_scopes(tokens, required_scopes)

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
                    params={
                        "user.fields": "subscription_type,profile_image_url,confirmed_email,name"
                    },
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
        try:
            profile = _XProfile.model_validate(data)
        except ValidationError:
            raise XPublisherError("X users/me returned malformed profile data") from None
        return XAccount(
            user_id=profile.id,
            handle=profile.username,
            subscription_type=profile.subscription_type,
            confirmed_email=str(profile.confirmed_email).lower()
            if profile.confirmed_email is not None
            else None,
            display_name=profile.name,
            photo_url=_larger_photo(str(profile.profile_image_url))
            if profile.profile_image_url is not None
            else None,
        )

    async def revoke(self, *, token: str, token_type_hint: TokenTypeHint) -> None:
        await _token_call(X_REVOKE_URL, {"token": token, "token_type_hint": token_type_hint})

    async def upload_media(
        self,
        *,
        token_for_call: TokenForCall,
        source: BinaryIO,
        byte_size: int,
        content_type: str,
        category: MediaCategory,
    ) -> str:
        async def headers() -> dict[str, str]:
            return {"Authorization": f"Bearer {await token_for_call()}"}

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                initialized = await _media_call(
                    client.post(
                        f"{X_MEDIA_UPLOAD_URL}/initialize",
                        json={
                            "media_type": content_type,
                            "total_bytes": byte_size,
                            "media_category": category,
                        },
                        headers=await headers(),
                    )
                )
                media_id = _media_data(initialized).get("id")
                if not isinstance(media_id, str) or not media_id:
                    raise XMediaUnavailableError("X's media initialize answered without an id")
                segment = 0
                while chunk := await asyncio.to_thread(source.read, MEDIA_CHUNK_BYTES):
                    append = client.post(
                        f"{X_MEDIA_UPLOAD_URL}/{media_id}/append",
                        data={"segment_index": str(segment)},
                        files={"media": ("media", chunk, "application/octet-stream")},
                        headers=await headers(),
                    )
                    try:
                        async with asyncio.timeout(_APPEND_LIMIT_SECONDS):
                            await _media_call(append)
                    except TimeoutError as error:
                        raise XMediaUnavailableError("X took too long to take a chunk") from error
                    segment += 1
                finalized = await _media_call(
                    client.post(
                        f"{X_MEDIA_UPLOAD_URL}/{media_id}/finalize", headers=await headers()
                    )
                )
                await _await_processing(
                    client,
                    media_id,
                    _media_data(finalized),
                    headers,
                    limit_seconds=_MEDIA_PROCESSING_SECONDS[category],
                )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as error:
            raise XNotReceivedError(f"X unreachable: {type(error).__name__}") from error
        except httpx.HTTPError as error:
            raise XMediaUnavailableError(
                f"X didn't answer uploading media: {type(error).__name__}"
            ) from error
        return media_id

    async def set_alt_text(self, *, access_token: str, media_id: str, alt_text: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                await _media_call(
                    client.post(
                        X_MEDIA_METADATA_URL,
                        json={"id": media_id, "metadata": {"alt_text": {"text": alt_text}}},
                        headers={"Authorization": f"Bearer {access_token}"},
                    )
                )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as error:
            raise XNotReceivedError(f"X unreachable: {type(error).__name__}") from error
        except httpx.HTTPError as error:
            raise XMediaUnavailableError(
                f"X didn't answer setting alt text: {type(error).__name__}"
            ) from error

    async def publish(
        self,
        *,
        access_token: str,
        text: str,
        community_id: Optional[str] = None,
        share_with_followers: bool = False,
        reply_to: Optional[str] = None,
        media_ids: Sequence[str] = (),
    ) -> str:
        body: dict[str, Any] = {"text": text}
        if media_ids:
            body["media"] = {"media_ids": list(media_ids)}
        if reply_to is not None:
            body["reply"] = {"in_reply_to_tweet_id": reply_to}
        elif community_id is not None:
            body["community_id"] = community_id
            # Also posts it to the followers' timelines, per X's developer changelog of Jul 28,
            # 2025; the English API reference wrongly ties it to super-follower posts.
            body["share_with_followers"] = share_with_followers
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    X_TWEETS_URL,
                    json=body,
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


async def _media_call(request: Awaitable[httpx.Response]) -> httpx.Response:
    """One call of a media upload, its failures mapped as `upload_media` says."""
    response = await request
    status = response.status_code
    if status in (200, 201, 202, 204):
        return response
    if status == 401:
        raise XReconnectNeededError("X refused the access token uploading media")
    if status == 429:
        raise XRateLimitedError("X rate limited uploading media")
    if status >= 500:
        raise XMediaUnavailableError(f"X answered HTTP {status} uploading media")
    raise XMediaRefusedError(status, _detail(response))


def _media_data(response: httpx.Response) -> dict[str, Any]:
    body = _json_or_none(response)
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, dict) else {}


async def _await_processing(
    client: httpx.AsyncClient,
    media_id: str,
    data: dict[str, Any],
    headers: Callable[[], Awaitable[dict[str, str]]],
    *,
    limit_seconds: float,
) -> None:
    """Polls STATUS until X has processed the upload; no `processing_info` means it is ready."""
    waited = 0.0
    while True:
        info = data.get("processing_info")
        if not isinstance(info, dict):
            return
        state = info.get("state")
        if state == "succeeded":
            return
        if state == "failed":
            error = info.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            raise XMediaRefusedError(
                None, message if isinstance(message, str) and message else "Processing failed."
            )
        wait = info.get("check_after_secs")
        wait = (
            min(float(wait), _MAX_POLL_WAIT_SECONDS) if isinstance(wait, int) and wait > 0 else 1.0
        )
        if waited + wait > limit_seconds:
            raise XMediaUnavailableError("X took too long to process media")
        await asyncio.sleep(wait)
        waited += wait
        status = await _media_call(
            client.get(
                X_MEDIA_UPLOAD_URL,
                params={"command": "STATUS", "media_id": media_id},
                headers=await headers(),
            )
        )
        data = _media_data(status)


def _larger_photo(url: str) -> str:
    """The `_200x200` variant of X's photo URL; a URL without `_normal` is kept as X gave it."""
    stem, dot, extension = url.rpartition(".")
    if not dot or "/" in extension:
        stem, dot, extension = url, "", ""
    if not stem.endswith(_SMALL_PHOTO_SUFFIX):
        return url
    return f"{stem[: -len(_SMALL_PHOTO_SUFFIX)]}{_LARGER_PHOTO_SUFFIX}{dot}{extension}"


def _tokens_from(
    body: dict[str, Any], *, now: datetime, previous_refresh_token: str, requested_scopes: str = ""
) -> XTokens:
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
    # An omitted scope means the requested scopes were granted (RFC 6749, section 5.1).
    scope = body.get("scope", requested_scopes)
    if "scope" in body and not isinstance(scope, str):
        raise XPublisherError("X returned malformed granted permissions")
    return XTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=now + timedelta(seconds=expires_in),
        scope=scope if isinstance(scope, str) else "",
    )


def _require_scopes(tokens: XTokens, required_scopes: str) -> XTokens:
    if not set(required_scopes.split()).issubset(tokens.scope.split()):
        raise XReconnectNeededError("X did not grant the required permissions")
    return tokens


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
    client_id, secret = settings.X_CLIENT_ID, settings.X_CLIENT_SECRET
    if not client_id or not secret:
        raise XPublisherNotConfiguredError()
    return client_id, secret, settings.x_redirect_uri()


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


@dataclass(frozen=True)
class FakeUpload:
    access_token: str
    data: bytes
    content_type: str
    category: MediaCategory
    media_id: str


@dataclass(frozen=True)
class FakeAltText:
    access_token: str
    media_id: str
    text: str


@dataclass
class FakeXPublisher:
    """
    X in memory. Every code exchange and refresh issues tokens `access-<id>-<n>` and
    `refresh-<id>-<n>` for `account`, n counting issues, valid for two hours; the authorize
    URL carries its query like X's. Records `exchanges` (code, verifier), `refreshes`
    (refresh tokens sent), `published` (access token, text), `published_to` (Community ID or
    None for the profile, share with followers) and `replied_to` (the X post id or None) of
    each publish, and `revoked` tokens. Set `fail_exchange`, `fail_refresh`,
    `fail_fetch_account` or `fail_publish` to an error to raise it, `fail_revoke` or
    `not_configured` to raise. `exchange_scope` and `refresh_scope` are the scope a code
    exchange and a refresh answer with, "" for none. With `fail_publish_on` set to n, only the
    nth publish call, counting from 1, raises `fail_publish`. Post ids are
    `1890000000000000000` plus the call's number. Records `uploads` and the `published_media`
    ids sent with each publish; `fail_upload` makes uploads raise it, and with `fail_upload_on`
    only the nth. Media ids are `1880000000000000000` plus the upload's number. An upload makes
    X's calls as the real one: initialize, one per `chunk_bytes` of the file, finalize, then
    `processing_polls` STATUS polls, counted in `upload_calls`, each with a token from
    `token_for_call` recorded in `upload_tokens`, and `while_calling_x_to_upload` awaited after
    it. Records `alt_texts` set, and `fail_alt_text` makes setting one raise it.
    `while_uploading`, `while_setting_alt_text` and `while_publishing`, when set, are awaited
    inside each such call.
    """

    account: XAccount = field(
        default_factory=lambda: XAccount(
            user_id="1001",
            handle="ada",
            subscription_type="None",
            confirmed_email="ada@example.com",
            display_name="Ada",
        )
    )
    exchanges: list[tuple[str, str]] = field(default_factory=list)
    refreshes: list[str] = field(default_factory=list)
    published: list[tuple[str, str]] = field(default_factory=list)
    published_to: list[tuple[Optional[str], bool]] = field(default_factory=list)
    replied_to: list[Optional[str]] = field(default_factory=list)
    published_media: list[list[str]] = field(default_factory=list)
    uploads: list[FakeUpload] = field(default_factory=list)
    alt_texts: list[FakeAltText] = field(default_factory=list)
    revoked: list[str] = field(default_factory=list)
    fail_exchange: Optional[XPublisherError] = None
    fail_refresh: Optional[XPublisherError] = None
    fail_publish: Optional[XPublisherError] = None
    fail_publish_on: Optional[int] = None
    fail_upload: Optional[XPublisherError] = None
    fail_upload_on: Optional[int] = None
    fail_alt_text: Optional[XPublisherError] = None
    fail_fetch_account: Optional[XPublisherError] = None
    while_uploading: Optional[Callable[[], Awaitable[None]]] = None
    while_calling_x_to_upload: Optional[Callable[[], Awaitable[None]]] = None
    while_setting_alt_text: Optional[Callable[[], Awaitable[None]]] = None
    while_publishing: Optional[Callable[[], Awaitable[None]]] = None
    fail_revoke: bool = False
    not_configured: bool = False
    exchange_scope: str = X_SCOPES
    refresh_scope: str = X_SCOPES
    issued: int = 0
    upload_attempts: int = 0
    chunk_bytes: int = MEDIA_CHUNK_BYTES
    processing_polls: int = 0
    upload_calls: int = 0
    upload_tokens: list[str] = field(default_factory=list)

    def build_authorize_url(
        self, *, state: str, code_challenge: str, scopes: str = X_SCOPES
    ) -> str:
        if self.not_configured:
            raise XPublisherNotConfiguredError()
        query = urlencode({"state": state, "code_challenge": code_challenge, "scope": scopes})
        return f"{X_AUTHORIZE_URL}?{query}"

    async def exchange_code(
        self, *, code: str, code_verifier: str, now: datetime, required_scopes: str = ""
    ) -> XTokens:
        self.exchanges.append((code, code_verifier))
        if self.fail_exchange is not None:
            raise self.fail_exchange
        return _require_scopes(
            replace(self._issue(now), scope=self.exchange_scope), required_scopes
        )

    async def refresh(self, *, refresh_token: str, now: datetime) -> XTokens:
        self.refreshes.append(refresh_token)
        if self.fail_refresh is not None:
            raise self.fail_refresh
        return replace(self._issue(now), scope=self.refresh_scope)

    async def fetch_account(self, *, access_token: str) -> XAccount:
        if self.fail_fetch_account is not None:
            raise self.fail_fetch_account
        return self.account

    async def publish(
        self,
        *,
        access_token: str,
        text: str,
        community_id: Optional[str] = None,
        share_with_followers: bool = False,
        reply_to: Optional[str] = None,
        media_ids: Sequence[str] = (),
    ) -> str:
        if self.while_publishing is not None:
            await self.while_publishing()
        self.published.append((access_token, text))
        self.published_to.append((community_id, share_with_followers))
        self.replied_to.append(reply_to)
        self.published_media.append(list(media_ids))
        if self.fail_publish is not None and self.fail_publish_on in (None, len(self.published)):
            raise self.fail_publish
        return str(1_890_000_000_000_000_000 + len(self.published))

    async def upload_media(
        self,
        *,
        token_for_call: TokenForCall,
        source: BinaryIO,
        byte_size: int,
        content_type: str,
        category: MediaCategory,
    ) -> str:
        self.upload_attempts += 1
        if self.while_uploading is not None:
            await self.while_uploading()
        if self.fail_upload is not None and self.fail_upload_on in (None, self.upload_attempts):
            raise self.fail_upload
        await self._call_x_to_upload(token_for_call)
        data = b""
        while chunk := source.read(self.chunk_bytes):
            await self._call_x_to_upload(token_for_call)
            data += chunk
        for _ in range(1 + self.processing_polls):
            await self._call_x_to_upload(token_for_call)
        media_id = str(1_880_000_000_000_000_000 + len(self.uploads) + 1)
        self.uploads.append(
            FakeUpload(
                access_token=self.upload_tokens[-1],
                data=data,
                content_type=content_type,
                category=category,
                media_id=media_id,
            )
        )
        return media_id

    async def _call_x_to_upload(self, token_for_call: TokenForCall) -> None:
        self.upload_tokens.append(await token_for_call())
        self.upload_calls += 1
        if self.while_calling_x_to_upload is not None:
            await self.while_calling_x_to_upload()

    async def set_alt_text(self, *, access_token: str, media_id: str, alt_text: str) -> None:
        if self.while_setting_alt_text is not None:
            await self.while_setting_alt_text()
        if self.fail_alt_text is not None:
            raise self.fail_alt_text
        self.alt_texts.append(
            FakeAltText(access_token=access_token, media_id=media_id, text=alt_text)
        )

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
