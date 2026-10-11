from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import pumpkit.scheduling.router as scheduling_router
from pumpkit.auth.mailer import announce_magic_link_delivery
from pumpkit.auth.router import router as auth_router
from pumpkit.authors.router import router as authors_router
from pumpkit.billing.router import router as billing_router
from pumpkit.core.analytics import posthog_client
from pumpkit.core.config import settings
from pumpkit.core.errors import register_exception_handlers
from pumpkit.core.logging import logger
from pumpkit.core.rate_limit import limiter
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
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# The prefix lives here so routers stay unaware of their mount point.
app.include_router(auth_router, prefix="/api/v1")
app.include_router(billing_router, prefix="/api/v1")
app.include_router(support_router, prefix="/api/v1")
app.include_router(authors_router, prefix="/api/v1")
app.include_router(posts_router, prefix="/api/v1")
app.include_router(scheduling_router.x_connection_router, prefix="/api/v1")
app.include_router(x_connection_router, prefix="/api/v1")
app.include_router(scheduling_router.x_authorization_router, prefix="/api/v1")
app.include_router(scheduling_router.router, prefix="/api/v1")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # pyright: ignore[reportArgumentType]

register_exception_handlers(app)
