from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routers import (
    auth_sessions,
    billing,
    first_party_auth,
    magic_link_auth,
    stripe,
    support,
    third_party_auth,
    users,
)
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logger import logger
from app.core.posthog import posthog_client
from app.core.rate_limit import limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up application...")
    # Do here everything you need to do before the application starts
    yield
    logger.info("Shutting down application...")
    # Flush any pending PostHog events before the process exits.
    posthog_client.shutdown()


# Setup FastAPI application
app = FastAPI(lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Add application routers
# Having the API prefix defined here makes everything centralized and
# keeps the routers unaware of their mount point (e.g., I could mount to /api/v2 later).
app.include_router(first_party_auth.router, prefix="/api/v1")
app.include_router(third_party_auth.router, prefix="/api/v1")
app.include_router(magic_link_auth.router, prefix="/api/v1")
app.include_router(auth_sessions.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(stripe.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")
app.include_router(support.router, prefix="/api/v1")

# Set up rate limiting and ensure rate limit exceptions are properly handled
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Register the global unhandled-exception handler.
register_exception_handlers(app)
