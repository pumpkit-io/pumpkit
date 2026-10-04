import re
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, status

import app.api.mediators.auth_sessions as auth_sessions_mediator
import app.api.mediators.magic_link_auth as magic_link_auth_mediator
import app.core.exceptions as exceptions_module


@pytest.fixture
def fake_posthog(monkeypatch) -> MagicMock:
    fake = MagicMock()
    monkeypatch.setattr(exceptions_module, "posthog_client", fake)
    return fake


async def test_unexpected_auth_error_returns_500_with_error_id_captured_once(
    client, monkeypatch, fake_posthog
):
    async def _boom(**_kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(auth_sessions_mediator, "refresh_token", _boom)

    response = await client.post("/api/v1/refresh-token")

    assert response.status_code == 500
    error_id = response.json()["error_id"]
    assert re.fullmatch(r"[0-9a-f]{8}", error_id)
    fake_posthog.capture_exception.assert_called_once()
    _, kwargs = fake_posthog.capture_exception.call_args
    assert kwargs["properties"]["error_id"] == error_id


async def test_intentional_http_exception_passes_through_uncaptured(
    client, monkeypatch, fake_posthog
):
    async def _unauthorized(**_kwargs):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing"
        )

    monkeypatch.setattr(auth_sessions_mediator, "refresh_token", _unauthorized)

    response = await client.post("/api/v1/refresh-token")

    assert response.status_code == 401
    assert response.json() == {"detail": "Refresh token missing"}
    fake_posthog.capture_exception.assert_not_called()


async def test_invalid_magic_link_redirects_to_login_error_page(client, monkeypatch, fake_posthog):
    async def _invalid(**_kwargs):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")

    monkeypatch.setattr(magic_link_auth_mediator, "complete_magic_link", _invalid)

    response = await client.get("/api/v1/login/magic-link", params={"token": "bad"})

    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:5173/login?error=invalid_magic_link"
    fake_posthog.capture_exception.assert_not_called()


async def test_unexpected_magic_link_error_reaches_global_handler(
    client, monkeypatch, fake_posthog
):
    async def _boom(**_kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(magic_link_auth_mediator, "complete_magic_link", _boom)

    response = await client.get("/api/v1/login/magic-link", params={"token": "whatever"})

    assert response.status_code == 500
    error_id = response.json()["error_id"]
    fake_posthog.capture_exception.assert_called_once()
    _, kwargs = fake_posthog.capture_exception.call_args
    assert kwargs["properties"]["error_id"] == error_id
