import math
import time

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.connected_apps import mediator
from pumpkit.connected_apps.schemas import AuthorizationServerMetadata, ProtectedResourceMetadata
from pumpkit.core.db.session import get_async_db
from pumpkit.core.rate_limit import limiter
from pumpkit.core.time import Clock, get_clock

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


# The OAuth endpoints, mounted under `/api/v1`. They answer errors as `{error, error_description}`.
oauth_router = APIRouter(tags=["oauth"])


@oauth_router.post("/oauth/register", status_code=201, response_model=None)
@limiter.limit("60/hour")
async def register_client(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    clock: Clock = Depends(get_clock),
) -> JSONResponse:
    return await mediator.register(request, db, now=clock())


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """slowapi's 429 for every route, except that OAuth routes answer in RFC 6749's error shape."""
    response = _rate_limit_exceeded_handler(request, exc)
    if not request.url.path.startswith("/api/v1/oauth/"):
        return response
    limit, key_args = request.state.view_rate_limit
    reset_time = limiter.limiter.get_window_stats(limit, *key_args).reset_time
    # The limiter counts in wall-clock time, not the app's Clock.
    retry_after = max(1, math.ceil(reset_time - time.time()))
    return JSONResponse(
        {
            "error": "temporarily_unavailable",
            "error_description": f"Too many requests ({exc.detail}). Try again later.",
        },
        status_code=429,
        headers={"Cache-Control": "no-store", "Retry-After": str(retry_after)},
    )
