import json
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.connected_apps.models import OAuthAuthorization, OAuthClient
from pumpkit.connected_apps.schemas import (
    AuthorizationDetailsResponse,
    AuthorizationServerMetadata,
    ClientRegistrationRequest,
    ClientRegistrationResponse,
    ConsentClient,
    ProtectedResourceMetadata,
    RedirectResponseBody,
)
from pumpkit.connected_apps.service import authorizations, clients, connections, retention
from pumpkit.connected_apps.service.redirect_uris import matches_registered, redirect_host
from pumpkit.connected_apps.service.tokens import SCOPE
from pumpkit.core.config import settings
from pumpkit.core.errors import NotFoundError
from pumpkit.core.rate_limit import hit_user_limit

_CLIENT_AUTH_METHODS = ["none", "client_secret_post", "client_secret_basic"]
_MAX_REGISTRATION_BYTES = 16 * 1024
# Printable ASCII: a registered id or a metadata document URL, never a NUL Postgres refuses.
_CLIENT_ID = re.compile(r"[\x21-\x7e]{1,2048}")
_CODE_CHALLENGE = re.compile(r"[A-Za-z0-9\-._~]{43,128}")
_MAX_STATE_LENGTH = 2048
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_REQUEST_GONE = "This request expired or was already used. Start connecting again from your app."


class OAuthError(Exception):
    """An error the mediator answers in RFC 6749's JSON shape, not the app's `detail` one."""

    def __init__(self, error: str, description: str, status_code: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code

    def response(self) -> JSONResponse:
        return JSONResponse(
            {"error": self.error, "error_description": self.description},
            status_code=self.status_code,
            headers={"Cache-Control": "no-store"},
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
    Where authorize sends the browser (guide section 4.4): the consent page with the stored
    request, the consent page with an error while the app's redirect URI is untrusted, or the
    redirect URI with an error once it is trusted.
    """
    values: dict[str, list[str]] = {}
    for name, value in params:
        values.setdefault(name, []).append(value)

    try:
        client, redirect_uri, redirect_uri_was_sent = await _trusted_redirect(db, values)
    except OAuthError as error:
        return _with_query(settings.oauth_consent_page_url(), {"error": error.error})

    sent_states = values.get("state", [])
    state = sent_states[0] if len(sent_states) == 1 and _is_valid_state(sent_states[0]) else None
    try:
        if sent_states and state is None:
            raise OAuthError(
                "invalid_request",
                f"state must be sent once, with at most {_MAX_STATE_LENGTH} characters "
                "and no control characters.",
            )
        code_challenge = _check_request(values)
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

    await retention.purge_expired(db, now=now)
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
    """The app, the redirect URI to answer on, and whether the request named it."""
    client_id = _single(values, "client_id", "invalid_client")
    client = None
    if client_id is not None and _CLIENT_ID.fullmatch(client_id):
        client = await clients.get_client(db, client_id)
    if client is None:
        raise OAuthError("invalid_client", "The app isn't registered with Pumpkit.")

    requested = _single(values, "redirect_uri", "invalid_redirect_uri")
    if requested is None and len(client.redirect_uris) == 1:
        return client, client.redirect_uris[0], False
    if requested is None or not matches_registered(requested, client.redirect_uris):
        raise OAuthError(
            "invalid_redirect_uri", "The return address doesn't match what the app registered."
        )
    return client, requested, True


def _check_request(values: dict[str, list[str]]) -> str:
    """The PKCE code challenge, once every parameter after the redirect URI checks out."""
    if _single(values, "response_type", "invalid_request") != "code":
        raise OAuthError("unsupported_response_type", "response_type must be code.")
    code_challenge = _single(values, "code_challenge", "invalid_request")
    if code_challenge is None or not _CODE_CHALLENGE.fullmatch(code_challenge):
        raise OAuthError("invalid_request", "PKCE is required: send a code_challenge.")
    # A missing method means plain, which leaks the verifier to whoever sees the request.
    if _single(values, "code_challenge_method", "invalid_request") != "S256":
        raise OAuthError("invalid_request", "code_challenge_method must be S256.")
    resource = _single(values, "resource", "invalid_target")
    if resource is not None and resource.removesuffix("/") != settings.mcp_url():
        raise OAuthError("invalid_target", f"resource must be {settings.mcp_url()}.")
    return code_challenge


def _single(values: dict[str, list[str]], name: str, error: str) -> Optional[str]:
    sent = values.get(name, [])
    if len(sent) > 1:
        raise OAuthError(error, f"{name} must be sent at most once.")
    return sent[0] if sent else None


def _is_valid_state(state: str) -> bool:
    return len(state) <= _MAX_STATE_LENGTH and not _CONTROL_CHARACTERS.search(state)


def _with_query(url: str, params: dict[str, Optional[str]]) -> str:
    """The URL with `params` appended, keeping any query it already has byte for byte."""
    parts = urlsplit(url)
    added = urlencode({name: value for name, value in params.items() if value is not None})
    query = f"{parts.query}&{added}" if parts.query else added
    return urlunsplit(parts._replace(query=query))


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
    """Hand the app a code for the User's connection to it, reusing one that is still active."""
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
