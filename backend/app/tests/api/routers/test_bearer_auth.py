"""Pins the Authorization-header contract of authenticated endpoints.

Unlike the shared `client` fixture, these tests do not override
`get_current_user`, so the real bearer-token extraction runs.
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token
from app.db.session import get_async_db
from app.main import app


@pytest_asyncio.fixture
async def raw_client(db_session_maker, user):
    async def _get_db():
        async with db_session_maker() as session:
            yield session

    app.dependency_overrides[get_async_db] = _get_db
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic YWxpY2U6c2VjcmV0"},
        {"Authorization": "Bearer"},
    ],
    ids=["missing", "wrong-scheme", "no-token"],
)
async def test_missing_or_malformed_header_is_401_bearer_challenge(raw_client, headers):
    response = await raw_client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_missing_header_detail(raw_client):
    response = await raw_client.get("/api/v1/users/me")
    assert response.json()["detail"] == "Not authenticated"


async def test_invalid_token_is_401_bearer_challenge(raw_client):
    response = await raw_client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["detail"] == "Could not validate credentials"


async def test_valid_token_authenticates(raw_client, user):
    token = create_access_token({"sub": str(user.id)})
    response = await raw_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"


async def test_suspended_user_is_401(raw_client, db, user):
    user.suspended_until = datetime.now(timezone.utc) + timedelta(days=1)
    await db.commit()
    token = create_access_token({"sub": str(user.id)})
    response = await raw_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_user_whose_suspension_ended_authenticates(raw_client, db, user):
    user.suspended_until = datetime.now(timezone.utc) - timedelta(days=1)
    await db.commit()
    token = create_access_token({"sub": str(user.id)})
    response = await raw_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
