"""Pins the Authorization-header contract of authenticated endpoints.

Unlike the shared `client` fixture, these browsers do not override
`get_current_user`, so the real bearer-token extraction runs, and tokens come
from a real sign-in.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import User


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic YWxpY2U6c2VjcmV0"},
        {"Authorization": "Bearer"},
    ],
    ids=["missing", "wrong-scheme", "no-token"],
)
async def test_missing_or_malformed_header_is_401_bearer_challenge(new_browser, headers):
    response = await new_browser().get("/api/v1/users/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_missing_header_detail(new_browser):
    response = await new_browser().get("/api/v1/users/me")
    assert response.json()["detail"] == "Not authenticated"


async def test_invalid_token_is_401_bearer_challenge(new_browser):
    response = await new_browser().get(
        "/api/v1/users/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["detail"] == "Could not validate credentials"


async def test_valid_token_authenticates(authed_client):
    response = await authed_client.get("/api/v1/users/me")
    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"


async def test_suspended_user_is_401(authed_client, suspend_user, user):
    await suspend_user(user.email)
    response = await authed_client.get("/api/v1/users/me")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_user_whose_suspension_ended_authenticates(authed_client, db, user: User):
    user.suspended_until = datetime.now(timezone.utc) - timedelta(days=1)
    db.add(user)
    await db.commit()
    response = await authed_client.get("/api/v1/users/me")
    assert response.status_code == 200
