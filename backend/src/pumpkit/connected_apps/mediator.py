from pumpkit.connected_apps.schemas import AuthorizationServerMetadata, ProtectedResourceMetadata
from pumpkit.core.config import settings

_CLIENT_AUTH_METHODS = ["none", "client_secret_post", "client_secret_basic"]


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
