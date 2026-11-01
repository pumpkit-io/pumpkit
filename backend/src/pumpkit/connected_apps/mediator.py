import json
from datetime import datetime

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.connected_apps.schemas import (
    AuthorizationServerMetadata,
    ClientRegistrationRequest,
    ClientRegistrationResponse,
    ProtectedResourceMetadata,
)
from pumpkit.connected_apps.service import clients, retention
from pumpkit.core.config import settings

_CLIENT_AUTH_METHODS = ["none", "client_secret_post", "client_secret_basic"]
_MAX_REGISTRATION_BYTES = 16 * 1024


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
        scopes_supported=["pumpkit"],
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
        scopes_supported=["pumpkit", "offline_access"],
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
    raw = await request.body()
    if len(raw) > _MAX_REGISTRATION_BYTES:
        raise _too_large()
    try:
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError
        return ClientRegistrationRequest.model_validate(document)
    except ValidationError as error:
        first = error.errors()[0]
        code = (
            "invalid_redirect_uri"
            if first["loc"][:1] == ("redirect_uris",)
            else "invalid_client_metadata"
        )
        where = ".".join(str(part) for part in first["loc"])
        raise OAuthError(code, f"{where}: {first['msg']}") from None
    except ValueError:
        raise OAuthError("invalid_client_metadata", "The body must be a JSON object.") from None


def _too_large() -> OAuthError:
    return OAuthError(
        "invalid_client_metadata",
        f"The request body can be at most {_MAX_REGISTRATION_BYTES // 1024} KB.",
        status_code=413,
    )
