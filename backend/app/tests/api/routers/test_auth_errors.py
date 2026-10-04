import re

from fastapi import HTTPException, status
from sqlalchemy import func, select

import app.api.mediators.magic_link_auth as magic_link_auth_mediator
import app.api.mediators.sessions as sessions_mediator
import app.api.services.refresh_tokens as refresh_tokens_service
import app.api.services.sessions as sessions
from app.db.models import User
from app.tests.conftest import magic_link_token


async def _boom(*_args, **_kwargs):
    raise RuntimeError("kaboom")


async def test_unexpected_auth_error_returns_500_with_error_id_captured_once(
    client, monkeypatch, assert_reported_500
):
    monkeypatch.setattr(sessions_mediator, "refresh_token", _boom)

    response = await client.post("/api/v1/refresh-token")

    assert_reported_500(response)


async def test_intentional_http_exception_passes_through_uncaptured(
    client, monkeypatch, fake_posthog
):
    async def _unauthorized(**_kwargs):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing"
        )

    monkeypatch.setattr(sessions_mediator, "refresh_token", _unauthorized)

    response = await client.post("/api/v1/refresh-token")

    assert response.status_code == 401
    assert response.json() == {"detail": "Refresh token missing"}
    fake_posthog.capture_exception.assert_not_called()


async def test_logout_without_session_succeeds(client, fake_posthog):
    response = await client.post("/api/v1/logout")

    assert response.status_code == 200
    assert response.json() == {"message": "Logged out successfully"}
    fake_posthog.capture_exception.assert_not_called()


async def test_unexpected_logout_failure_reaches_global_handler(
    authed_client, monkeypatch, assert_reported_500
):
    monkeypatch.setattr(refresh_tokens_service, "revoke_session", _boom)

    response = await authed_client.post("/api/v1/logout")

    assert_reported_500(response)


async def test_invalid_magic_link_redirects_to_the_sign_in_page(client, fake_posthog):
    response = await client.get("/api/v1/login/magic-link", params={"token": "not-a-real-token"})

    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:5173/login?error=invalid_magic_link"
    fake_posthog.capture_exception.assert_not_called()


async def test_other_http_exception_on_magic_link_is_not_turned_into_a_redirect(
    client, monkeypatch, fake_posthog
):
    async def _unavailable(**_kwargs):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Try again later"
        )

    monkeypatch.setattr(magic_link_auth_mediator, "complete_magic_link", _unavailable)

    response = await client.get("/api/v1/login/magic-link", params={"token": "whatever"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Try again later"}
    fake_posthog.capture_exception.assert_not_called()


async def test_unexpected_magic_link_error_is_reported_and_lands_on_sign_in_failed(
    new_browser, auth_outbox, monkeypatch, fake_posthog, db
):
    browser = new_browser()
    requested = await browser.post(
        "/api/v1/login/magic-link/request", json={"email": "newcomer@example.com"}
    )
    assert requested.status_code == 200
    monkeypatch.setattr(sessions, "start", _boom)

    opened = await browser.get(
        "/api/v1/login/magic-link",
        params={"token": magic_link_token(auth_outbox.messages[-1].link_url)},
    )

    assert opened.status_code == 303
    assert opened.headers["location"] == "http://localhost:5173/login?error=sign_in_failed"
    assert "refresh_token" not in browser.cookies
    fake_posthog.capture_exception.assert_called_once()
    assert re.fullmatch(
        r"[0-9a-f]{8}", fake_posthog.capture_exception.call_args.kwargs["properties"]["error_id"]
    )
    # The sign-in was rolled back: the User it created doesn't survive the failure.
    assert (await db.execute(select(func.count()).select_from(User))).scalar_one() == 0
