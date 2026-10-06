from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.routers import (
    billing,
    google_auth,
    inspiration_authors,
    magic_link_auth,
    posts,
    sessions,
    support,
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
    yield
    logger.info("Shutting down application...")
    # Flush any pending PostHog events before the process exits.
    posthog_client.shutdown()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# The prefix lives here so routers stay unaware of their mount point.
app.include_router(google_auth.router, prefix="/api/v1")
app.include_router(magic_link_auth.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")
app.include_router(support.router, prefix="/api/v1")
app.include_router(inspiration_authors.router, prefix="/api/v1")
app.include_router(posts.router, prefix="/api/v1")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # pyright: ignore[reportArgumentType]

register_exception_handlers(app)
