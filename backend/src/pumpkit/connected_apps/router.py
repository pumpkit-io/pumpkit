from fastapi import APIRouter

from pumpkit.connected_apps import mediator
from pumpkit.connected_apps.schemas import AuthorizationServerMetadata, ProtectedResourceMetadata

# Discovery lives at the origin's root, outside the `/api/v1` prefix `main` gives other routers.
discovery_router = APIRouter(tags=["oauth"])


# The path-inserted location (RFC 9728) and the root one, for clients that try only one.
@discovery_router.get("/.well-known/oauth-protected-resource/api/v1/mcp")
@discovery_router.get("/.well-known/oauth-protected-resource")
async def get_protected_resource_metadata() -> ProtectedResourceMetadata:
    return mediator.protected_resource_metadata()


@discovery_router.get("/.well-known/oauth-authorization-server")
async def get_authorization_server_metadata() -> AuthorizationServerMetadata:
    return mediator.authorization_server_metadata()
