from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.routing import Route

import pumpkit.mcp_server as mcp_server
import pumpkit.scheduling.router as scheduling_router
from pumpkit.auth.mailer import announce_magic_link_delivery
from pumpkit.auth.router import api_keys_router
from pumpkit.auth.router import router as auth_router
from pumpkit.authors.router import router as authors_router
from pumpkit.billing.dependencies import require_subscribed_user
from pumpkit.billing.router import router as billing_router
from pumpkit.connected_apps.router import discovery_router
from pumpkit.core.analytics import posthog_client
from pumpkit.core.config import settings
from pumpkit.core.errors import register_exception_handlers
from pumpkit.core.logging import logger
from pumpkit.core.open_cors import OpenCorsMiddleware
from pumpkit.core.rate_limit import limiter
from pumpkit.onboarding.router import router as onboarding_router
from pumpkit.posts.router import router as posts_router
from pumpkit.support.router import router as support_router
from pumpkit.x_connection.router import router as x_connection_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up application...")
    announce_magic_link_delivery()
    yield
    logger.info("Shutting down application...")
    # Flush any pending PostHog events before the process exits.
    posthog_client.shutdown()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Added last, so outermost: it answers the open paths before the strict policy above sees them.
app.add_middleware(OpenCorsMiddleware)

# The prefix lives here so routers stay unaware of their mount point.
app.include_router(auth_router, prefix="/api/v1")
# Billing's access rule gates API keys here, since auth sits below billing (ADR 0008).
app.include_router(
    api_keys_router, prefix="/api/v1", dependencies=[Depends(require_subscribed_user)]
)
app.include_router(billing_router, prefix="/api/v1")
app.include_router(support_router, prefix="/api/v1")
app.include_router(authors_router, prefix="/api/v1")
app.include_router(posts_router, prefix="/api/v1")
app.include_router(scheduling_router.posts_router, prefix="/api/v1")
app.include_router(scheduling_router.x_connection_router, prefix="/api/v1")
app.include_router(x_connection_router, prefix="/api/v1")
app.include_router(scheduling_router.x_authorization_router, prefix="/api/v1")
app.include_router(scheduling_router.router, prefix="/api/v1")
app.include_router(scheduling_router.usage_router, prefix="/api/v1")
app.include_router(onboarding_router, prefix="/api/v1")
app.include_router(discovery_router)
# A Route, not a Mount, so the URL has no trailing slash. GET and DELETE reach the endpoint so
# it can answer them after authenticating.
app.router.routes.append(
    Route("/api/v1/mcp", endpoint=mcp_server.endpoint, methods=["POST", "GET", "DELETE"])
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # pyright: ignore[reportArgumentType]

register_exception_handlers(app)
