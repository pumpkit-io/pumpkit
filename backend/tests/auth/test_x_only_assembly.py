from urllib.parse import parse_qs, urlsplit

import pytest

from pumpkit.core.config import settings
from pumpkit.x_connection.x_publisher import X_SIGN_IN_SCOPES


@pytest.fixture(autouse=True)
def inactive_credentials_configured(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "unused-google-client")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "unused-google-secret")
    monkeypatch.setattr(settings, "SMTP_HOST", "unused-smtp.example")
    monkeypatch.setattr(settings, "EMAIL_FROM", "unused@example.com")


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("GET", "/login/google", None),
        ("GET", "/oauth/google/callback?code=old&state=old", None),
        ("POST", "/login/magic-link/request", {"email": "person@example.com"}),
        ("GET", "/login/magic-link?token=old", None),
        ("GET", "/login/magic-link/inbox-redirect", None),
    ],
)
async def test_legacy_sign_in_is_unavailable_in_the_assembled_app(
    new_browser, method, path, payload
):
    response = await new_browser().request(method, f"/api/v1{path}", json=payload)

    assert response.status_code == 404
    assert "refresh_token" not in response.cookies


async def test_only_x_is_advertised_even_with_google_configured(new_browser):
    response = await new_browser().get("/api/v1/instance")

    assert response.status_code == 200
    assert response.json()["sign_in_methods"] == ["x"]


async def test_x_completion_is_mounted_but_rejects_an_unbound_attempt(new_browser):
    response = await new_browser().post(
        "/api/v1/login/x/complete", json={"state": "unbound", "code": "unused"}
    )

    assert response.status_code == 400
    assert "refresh_token" not in response.cookies


async def test_x_opens_a_session_that_refreshes_and_logs_out_in_the_assembled_app(
    new_browser, fake_x_publisher, auth_outbox
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    browser = new_browser()
    started = await browser.get("/api/v1/login/x")
    assert started.status_code == 200
    state = parse_qs(urlsplit(started.json()["url"]).query)["state"][0]
    signed_in = await browser.post(
        "/api/v1/login/x/complete", json={"state": state, "code": "bound"}
    )
    assert signed_in.status_code == 200
    first_cookie = browser.cookies["refresh_token"]
    me = await browser.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer " + signed_in.json()["access_token"]}
    )
    assert me.status_code == 200
    assert me.json()["x_handle"] == "ada"
    refreshed = await browser.post("/api/v1/refresh-token")
    assert refreshed.status_code == 200
    assert browser.cookies["refresh_token"] != first_cookie
    assert auth_outbox.messages == []
    assert (await browser.post("/api/v1/logout")).status_code == 200
    assert (await browser.post("/api/v1/refresh-token")).status_code == 401
