import base64
import binascii
import json
import re
from datetime import datetime
from typing import Optional
from urllib.parse import unquote_plus, urlencode, urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.auth.service import users
from pumpkit.auth.service.sessions import may_hold_session
from pumpkit.connected_apps.models import AppConnection, OAuthAuthorization, OAuthClient
from pumpkit.connected_apps.schemas import (
    AuthorizationDetailsResponse,
    AuthorizationServerMetadata,
    ClientRegistrationRequest,
    ClientRegistrationResponse,
    ConsentClient,
    ProtectedResourceMetadata,
    RedirectResponseBody,
    TokenResponse,
)
from pumpkit.connected_apps.service import authorizations, clients, connections, retention, tokens
from pumpkit.connected_apps.service.redirect_uris import matches_registered, redirect_host
from pumpkit.connected_apps.service.tokens import (
    ACCESS_TOKEN_LIFETIME,
    REFRESH_REUSE_GRACE,
    SCOPE,
)
from pumpkit.core.config import settings
from pumpkit.core.errors import NotFoundError
from pumpkit.core.logging import logger
from pumpkit.core.rate_limit import hit_user_limit
from pumpkit.core.time import as_utc

_CLIENT_AUTH_METHODS = ["none", "client_secret_post", "client_secret_basic"]
_MAX_REGISTRATION_BYTES = 16 * 1024
# Printable ASCII: a registered id or a metadata document URL, never a NUL Postgres refuses.
_CLIENT_ID = re.compile(r"[\x21-\x7e]{1,2048}")
_CODE_CHALLENGE = re.compile(r"[A-Za-z0-9\-._~]{43,128}")
_MAX_STATE_LENGTH = 2048
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_REQUEST_GONE = "This request expired or was already used. Start connecting again from your app."


# RFC 6749 section 5.1: no cache may keep an answer that can carry a token or a code.
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class OAuthError(Exception):
    """An error the mediator answers in RFC 6749's JSON shape, not the app's `detail` one."""

    def __init__(
        self,
        error: str,
        description: str = "",
        status_code: int = 400,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code
        self.headers = headers or {}

    def response(self) -> JSONResponse:
        return JSONResponse(
            {"error": self.error, "error_description": self.description},
            status_code=self.status_code,
            headers={**NO_STORE, **self.headers},
        )


def protected_resource_metadata() -> ProtectedResourceMetadata:
    return ProtectedResourceMetadata(
        resource=settings.mcp_url(),
        authorization_servers=[settings.oauth_issuer()],
        scopes_supported=[SCOPE],
        bearer_methods_supported=["header"],
        resource_name=settings.APP_NAME,
    )


def authorization_server_metadata() -> AuthorizationServerMetadata:
    return AuthorizationServerMetadata(
        issuer=settings.oauth_issuer(),
        authorization_endpoint=settings.oauth_endpoint("authorize"),
        token_endpoint=settings.oauth_endpoint("token"),
        registration_endpoint=settings.oauth_endpoint("register"),
        revocation_endpoint=settings.oauth_endpoint("revoke"),
        # `offline_access` is advertised for clients that ask for it; the token endpoint ignores it.
        scopes_supported=[SCOPE, "offline_access"],
        response_types_supported=["code"],
        response_modes_supported=["query"],
        grant_types_supported=["authorization_code", "refresh_token"],
        code_challenge_methods_supported=["S256"],
        token_endpoint_auth_methods_supported=_CLIENT_AUTH_METHODS,
        revocation_endpoint_auth_methods_supported=_CLIENT_AUTH_METHODS,
        authorization_response_iss_parameter_supported=True,
    )


async def register(request: Request, db: AsyncSession, *, now: datetime) -> JSONResponse:
    try:
        metadata = await _read_registration(request)
    except OAuthError as error:
        return error.response()

    await retention.purge_expired(db, now=now)
    client, secret = await clients.register_client(db, metadata, now=now)
    await db.commit()

    body = ClientRegistrationResponse(
        client_id=client.id,
        client_id_issued_at=int(now.timestamp()),
        client_secret=secret,
        client_secret_expires_at=0 if secret else None,
        redirect_uris=client.redirect_uris,
        client_name=client.name,
        token_endpoint_auth_method=metadata.token_endpoint_auth_method,
        grant_types=metadata.grant_types,
        response_types=metadata.response_types,
        client_uri=client.client_uri,
        logo_uri=client.logo_uri,
        software_id=client.software_id,
        software_version=client.software_version,
    )
    return JSONResponse(
        body.model_dump(exclude_none=True),
        status_code=201,
        headers={"Cache-Control": "no-store"},
    )


async def _read_registration(request: Request) -> ClientRegistrationRequest:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > _MAX_REGISTRATION_BYTES:
        raise _too_large()
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > _MAX_REGISTRATION_BYTES:
            raise _too_large()

    try:
        document = json.loads(raw)
    # Deeply nested arrays under the size cap exhaust the parser's recursion.
    except (ValueError, RecursionError):
        document = None
    if not isinstance(document, dict):
        raise OAuthError("invalid_client_metadata", "The body must be a JSON object.")

    try:
        return ClientRegistrationRequest.model_validate(document)
    except ValidationError as error:
        first = error.errors()[0]
        field = ".".join(str(part) for part in first["loc"])
        message = first["msg"].removeprefix("Value error, ")
        code = (
            "invalid_redirect_uri"
            if field.startswith("redirect_uris")
            else "invalid_client_metadata"
        )
        raise OAuthError(code, f"{field}: {message}" if field else message) from None


def _too_large() -> OAuthError:
    return OAuthError(
        "invalid_client_metadata",
        f"The request body can be at most {_MAX_REGISTRATION_BYTES // 1024} KB.",
    )


async def start_authorization(
    params: list[tuple[str, str]], db: AsyncSession, *, now: datetime
) -> str:
    """
    Where authorize sends the browser: the consent page with the stored request, the consent
    page with an error while the app's redirect URI is untrusted, or the redirect URI with an
    error once it is trusted. Parameters are checked in RFC 6749's order, `state` last.
    """
    values = _grouped(params)

    # Before the lookup, so it can't delete the app this request's row goes on to point at.
    await retention.purge_expired(db, now=now)
    try:
        client, redirect_uri, redirect_uri_was_sent = await _trusted_redirect(db, values)
    except OAuthError as error:
        return _with_query(settings.oauth_consent_page_url(), {"error": error.error})

    sent_states = values.get("state", [])
    state = sent_states[0] if len(sent_states) == 1 and _is_valid_state(sent_states[0]) else None
    try:
        code_challenge = _check_request(values)
        if sent_states and state is None:
            raise OAuthError(
                "invalid_request",
                f"state must be sent once, with at most {_MAX_STATE_LENGTH} characters "
                "and no control characters.",
            )
    except OAuthError as error:
        return _with_query(
            redirect_uri,
            {
                "error": error.error,
                "error_description": error.description,
                "state": state,
                "iss": settings.oauth_issuer(),
            },
        )

    authorization = await authorizations.create_pending(
        db,
        client_id=client.id,
        redirect_uri=redirect_uri,
        redirect_uri_was_sent=redirect_uri_was_sent,
        code_challenge=code_challenge,
        # Unknown scopes such as offline_access are dropped, and every app gets the one scope.
        scope=SCOPE,
        resource=settings.mcp_url(),
        state=state,
        now=now,
    )
    await db.commit()
    return _with_query(settings.oauth_consent_page_url(), {"request": authorization.id})


async def _trusted_redirect(
    db: AsyncSession, values: dict[str, list[str]]
) -> tuple[OAuthClient, str, bool]:
    """
    The app, the redirect URI to answer on, and whether the request named it. Errors carry only
    a code, since the consent page explains each one in its own words.
    """
    client_id = _single(values, "client_id", "invalid_client")
    client = None
    if client_id is not None and _CLIENT_ID.fullmatch(client_id):
        client = await clients.get_client(db, client_id)
    if client is None:
        raise OAuthError("invalid_client")

    requested = _single(values, "redirect_uri", "invalid_redirect_uri")
    if requested is None and len(client.redirect_uris) == 1:
        return client, client.redirect_uris[0], False
    if requested is None or not matches_registered(requested, client.redirect_uris):
        raise OAuthError("invalid_redirect_uri")
    return client, requested, True


def _check_request(values: dict[str, list[str]]) -> str:
    """The PKCE code challenge, once every parameter after the redirect URI checks out."""
    response_type = _single(values, "response_type", "invalid_request")
    if response_type is None:
        raise OAuthError("invalid_request", "response_type is required: send code.")
    if response_type != "code":
        raise OAuthError("unsupported_response_type", "response_type must be code.")
    code_challenge = _single(values, "code_challenge", "invalid_request")
    if code_challenge is None or not _CODE_CHALLENGE.fullmatch(code_challenge):
        raise OAuthError("invalid_request", "PKCE is required: send a code_challenge.")
    # A missing method means plain, which leaks the verifier to whoever sees the request.
    if _single(values, "code_challenge_method", "invalid_request") != "S256":
        raise OAuthError("invalid_request", "code_challenge_method must be S256.")
    _check_resource(values)
    return code_challenge


def _check_resource(values: dict[str, list[str]]) -> None:
    """RFC 8707: an app that names a resource may name only the MCP URL (ADR 0020)."""
    resource = _single(values, "resource", "invalid_target")
    if resource is not None and resource.removesuffix("/") != settings.mcp_url():
        raise OAuthError("invalid_target", f"resource must be {settings.mcp_url()}.")


def _grouped(params: list[tuple[str, str]]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for name, value in params:
        values.setdefault(name, []).append(value)
    return values


def _single(values: dict[str, list[str]], name: str, error: str) -> Optional[str]:
    sent = values.get(name, [])
    if len(sent) > 1:
        raise OAuthError(error, f"{name} must be sent at most once.")
    return sent[0] if sent else None


def _is_valid_state(state: str) -> bool:
    return len(state) <= _MAX_STATE_LENGTH and not _CONTROL_CHARACTERS.search(state)


def _with_query(url: str, params: dict[str, Optional[str]]) -> str:
    """
    The URL with `params` appended, keeping the rest byte for byte: re-serializing it would turn
    `app:///cb` into `app:/cb`. Redirect URIs never carry a fragment, so the query ends the URL.
    """
    added = urlencode({name: value for name, value in params.items() if value is not None})
    if url.endswith(("?", "&")):
        separator = ""
    else:
        separator = "&" if "?" in url else "?"
    return f"{url}{separator}{added}"


async def authorization_details(
    db: AsyncSession, authorization_id: str, *, now: datetime
) -> AuthorizationDetailsResponse:
    authorization, client = await _get_pending(db, authorization_id, now=now)
    host = redirect_host(authorization.redirect_uri)
    return AuthorizationDetailsResponse(
        client=ConsentClient(
            name=client.name,
            verified_domain=(
                urlsplit(client.id).hostname if client.kind == "metadata_document" else None
            ),
            redirect_host=host,
            is_local=host is None,
        ),
        scope=authorization.scope,
        expires_at=authorization.expires_at,
    )


async def approve_authorization(
    db: AsyncSession, user: User, authorization_id: str, *, now: datetime
) -> RedirectResponseBody:
    """Hand the app a code for the User's connection to it, reusing an unrevoked one."""
    hit_user_limit("approve_authorization", user.id, "20/minute")
    authorization, _ = await _get_pending(db, authorization_id, now=now)
    connection = await connections.find_or_create(
        db,
        user_id=user.id,
        client_id=authorization.client_id,
        scope=authorization.scope,
        resource=authorization.resource,
        now=now,
    )
    code = await authorizations.approve(
        db, authorization, user_id=user.id, app_connection_id=connection.id, now=now
    )
    if code is None:
        raise NotFoundError(_REQUEST_GONE)
    redirect_url = _with_query(
        authorization.redirect_uri,
        {"code": code, "state": authorization.state, "iss": settings.oauth_issuer()},
    )
    await db.commit()
    return RedirectResponseBody(redirect_url=redirect_url)


async def deny_authorization(
    db: AsyncSession, user: User, authorization_id: str, *, now: datetime
) -> RedirectResponseBody:
    authorization, _ = await _get_pending(db, authorization_id, now=now)
    if not await authorizations.deny(db, authorization, user_id=user.id, now=now):
        raise NotFoundError(_REQUEST_GONE)
    redirect_url = _with_query(
        authorization.redirect_uri,
        {
            "error": "access_denied",
            "error_description": "The user refused to connect the app.",
            "state": authorization.state,
            "iss": settings.oauth_issuer(),
        },
    )
    await db.commit()
    return RedirectResponseBody(redirect_url=redirect_url)


async def _get_pending(
    db: AsyncSession, authorization_id: str, *, now: datetime
) -> tuple[OAuthAuthorization, OAuthClient]:
    pending = await authorizations.get_pending(db, authorization_id, now=now)
    if pending is None:
        raise NotFoundError(_REQUEST_GONE)
    return pending


async def token(
    params: list[tuple[str, str]],
    authorization_header: Optional[str],
    db: AsyncSession,
    *,
    now: datetime,
) -> JSONResponse:
    """Redeem a code or rotate a refresh token for a new access and refresh token pair."""
    values = _grouped(params)
    try:
        client = await _authenticate_client(db, values, authorization_header)
        grant_type = _single(values, "grant_type", "invalid_request")
        if grant_type == "authorization_code":
            issued = await _redeem_code(db, client, values, now=now)
        elif grant_type == "refresh_token":
            issued = await _refresh(db, client, values, now=now)
        elif grant_type is None:
            raise OAuthError("invalid_request", "grant_type is required.")
        else:
            raise OAuthError(
                "unsupported_grant_type", "grant_type must be authorization_code or refresh_token."
            )
    except OAuthError as error:
        # Commit refusals too: a reused code or refresh token disconnects its app.
        await db.commit()
        return error.response()

    await db.commit()
    body = TokenResponse(
        access_token=issued.access_token,
        expires_in=int(ACCESS_TOKEN_LIFETIME.total_seconds()),
        refresh_token=issued.refresh_token,
        scope=SCOPE,
    )
    return JSONResponse(body.model_dump(), headers=NO_STORE)


async def _authenticate_client(
    db: AsyncSession, values: dict[str, list[str]], authorization_header: Optional[str]
) -> OAuthClient:
    """
    The app, by HTTP Basic or by `client_id` and `client_secret` in the body (RFC 6749 section
    2.3.1). An app registered with a secret must present it; a public app's secret is ignored.
    """
    client_id = _single(values, "client_id", "invalid_request")
    secret = _single(values, "client_secret", "invalid_request")
    challenge = None
    scheme, _, credentials = (authorization_header or "").partition(" ")
    if scheme.lower() == "basic":
        # RFC 6749 section 2.3.1: an app that used Basic is told to retry with it.
        challenge = {"WWW-Authenticate": 'Basic realm="pumpkit"'}
        basic = _basic_credentials(credentials)
        if basic is None or client_id not in (None, basic[0]):
            raise OAuthError(
                "invalid_client", "The Basic credentials are malformed.", 401, challenge
            )
        client_id, secret = basic

    client = None
    if client_id is not None and _CLIENT_ID.fullmatch(client_id):
        client = await clients.authenticate(db, client_id, secret)
    if client is None:
        raise OAuthError(
            "invalid_client", "The app is unknown or its secret is wrong.", 401, challenge
        )
    return client


def _basic_credentials(credentials: str) -> Optional[tuple[str, str]]:
    """The client id and secret of a Basic header, or None when it is malformed."""
    try:
        decoded = base64.b64decode(credentials, validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        return None
    client_id, colon, secret = decoded.partition(":")
    if not colon:
        return None
    return unquote_plus(client_id), unquote_plus(secret)


async def _redeem_code(
    db: AsyncSession, client: OAuthClient, values: dict[str, list[str]], *, now: datetime
) -> tokens.IssuedTokens:
    """RFC 6749 section 4.1.3, with PKCE (RFC 7636) and the code's single use (OAuth 2.1)."""
    code = _single(values, "code", "invalid_request")
    if code is None:
        raise OAuthError("invalid_request", "code is required.")
    found = await authorizations.find_code(db, code, now=now)
    if found is None:
        raise OAuthError("invalid_grant", "The code is unknown or expired.")
    authorization, connection = found
    if authorization.exchanged_at is not None:
        raise await _code_reused(db, connection, now=now)
    if authorization.client_id != client.id:
        raise OAuthError("invalid_grant", "The code was issued to another app.")

    redirect_uri = _single(values, "redirect_uri", "invalid_request")
    missing = redirect_uri is None and authorization.redirect_uri_was_sent
    if missing or (redirect_uri is not None and redirect_uri != authorization.redirect_uri):
        raise OAuthError("invalid_grant", "redirect_uri must be the one sent to authorize.")
    verifier = _single(values, "code_verifier", "invalid_request")
    if verifier is None or not authorizations.pkce_matches(verifier, authorization.code_challenge):
        raise OAuthError("invalid_grant", "code_verifier doesn't match the code_challenge.")
    _check_resource(values)
    if connection.revoked_at is not None or not await _may_connect(db, connection.user_id):
        raise OAuthError("invalid_grant", "The user disconnected the app or can't use Pumpkit.")

    if not await authorizations.mark_exchanged(db, authorization.id, now=now):
        raise await _code_reused(db, connection, now=now)
    return await tokens.issue_pair(db, app_connection_id=connection.id, now=now)


async def _code_reused(db: AsyncSession, connection: AppConnection, *, now: datetime) -> OAuthError:
    # OAuth 2.1 section 4.1.3: whoever holds a copy of a used code may hold its tokens too.
    logger.error(
        "Authorization code reuse detected: disconnecting app (app_connection_id=%s, user_id=%s)",
        connection.id,
        connection.user_id,
    )
    await connections.revoke(db, connection.id, now=now)
    return OAuthError("invalid_grant", "The code was already used. The app is disconnected.")


async def _refresh(
    db: AsyncSession, client: OAuthClient, values: dict[str, list[str]], *, now: datetime
) -> tokens.IssuedTokens:
    """RFC 6749 section 6, rotating the refresh token every time (OAuth 2.1 section 4.3.1)."""
    refresh_token = _single(values, "refresh_token", "invalid_request")
    if refresh_token is None:
        raise OAuthError("invalid_request", "refresh_token is required.")
    found = await tokens.find_refresh_token(db, refresh_token)
    if found is None or found[1].client_id != client.id or found[1].revoked_at is not None:
        raise OAuthError(
            "invalid_grant", "The refresh token is unknown or the app is disconnected."
        )
    presented, connection = found
    rotated_at = presented.rotated_at
    if rotated_at is not None and as_utc(rotated_at) + REFRESH_REUSE_GRACE < now:
        # Someone holds a copy of a token exchanged a while ago: likely theft.
        logger.error(
            "Refresh token reuse detected: disconnecting app (app_connection_id=%s, user_id=%s)",
            connection.id,
            connection.user_id,
        )
        await connections.revoke(db, connection.id, now=now)
        raise OAuthError("invalid_grant", "The refresh token was already used.")
    if presented.revoked_at is not None or as_utc(presented.expires_at) <= now:
        raise OAuthError("invalid_grant", "The refresh token expired or was revoked.")
    if not await _may_connect(db, connection.user_id):
        raise OAuthError("invalid_grant", "The user can't use Pumpkit.")
    _check_resource(values)
    return await tokens.rotate(db, presented, now=now)


async def revoke(
    params: list[tuple[str, str]],
    authorization_header: Optional[str],
    db: AsyncSession,
    *,
    now: datetime,
) -> Response:
    """
    RFC 7009: a refresh token disconnects its app, an access token dies alone. Unknown tokens
    and other apps' tokens get the same 200, so the answer reveals nothing about them.
    """
    values = _grouped(params)
    try:
        client = await _authenticate_client(db, values, authorization_header)
        token = _single(values, "token", "invalid_request")
        if token is None:
            raise OAuthError("invalid_request", "token is required.")
    except OAuthError as error:
        return error.response()

    # Both kinds are looked up whatever `token_type_hint` says, which RFC 7009 allows.
    found_refresh = await tokens.find_refresh_token(db, token)
    if found_refresh is not None:
        if found_refresh[1].client_id == client.id:
            await connections.revoke(db, found_refresh[1].id, now=now)
    else:
        found_access = await tokens.find_access_token(db, token)
        if found_access is not None and found_access[1].client_id == client.id:
            access_token, _ = found_access
            if access_token.revoked_at is None:
                access_token.revoked_at = now
    await db.commit()
    return Response(status_code=200, headers=NO_STORE)


async def _may_connect(db: AsyncSession, user_id: str) -> bool:
    """Whether the User exists and isn't Suspended, the rule a Session follows too."""
    user = await users.get_user_by_id(db, user_id)
    return user is not None and may_hold_session(user)
