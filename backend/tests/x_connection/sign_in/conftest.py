import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from slowapi.errors import RateLimitExceeded

from pumpkit.auth.router import router as auth_router
from pumpkit.connected_apps.router import rate_limit_exceeded_handler
from pumpkit.core.db.session import get_async_db
from pumpkit.core.errors import register_exception_handlers
from pumpkit.core.rate_limit import limiter
from pumpkit.core.time import get_clock
from pumpkit.x_connection.sign_in_router import router
from pumpkit.x_connection.x_publisher import get_x_publisher


@pytest.fixture
async def sign_in_app(db_session_maker, fake_x_publisher, fixed_clock):
    staged = FastAPI()
    staged.state.limiter = limiter
    staged.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # pyright: ignore[reportArgumentType]
    register_exception_handlers(staged)
    staged.include_router(router, prefix="/api/v1")
    staged.include_router(auth_router, prefix="/api/v1")

    async def get_db():
        async with db_session_maker() as session:
            yield session

    staged.dependency_overrides[get_async_db] = get_db
    staged.dependency_overrides[get_x_publisher] = lambda: fake_x_publisher
    staged.dependency_overrides[get_clock] = lambda: fixed_clock
    return staged


@pytest.fixture
async def sign_in_browser(sign_in_app):
    async with AsyncClient(
        transport=ASGITransport(app=sign_in_app), base_url="http://test"
    ) as browser:
        yield browser
