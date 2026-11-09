from urllib.parse import parse_qs, urlsplit

import pytest

from pumpkit.core.config import settings
from pumpkit.x_connection.x_publisher import OfficialXPublisher, get_x_publisher


async def test_a_signed_out_browser_can_begin_x_sign_in_without_a_user(sign_in_browser):
    started = await sign_in_browser.get("/api/v1/login/x")

    assert started.status_code == 200
    query = parse_qs(urlsplit(started.json()["url"]).query)
    assert set(query["scope"][0].split()) == {
        "tweet.read",
        "tweet.write",
        "users.read",
        "offline.access",
        "media.write",
        "users.email",
    }
    assert query["state"][0]
    assert query["code_challenge"][0]
    assert "refresh_token" not in sign_in_browser.cookies
    assert started.headers["cache-control"] == "no-store"


async def test_sign_in_refuses_an_external_return_destination(sign_in_browser):
    started = await sign_in_browser.get(
        "/api/v1/login/x", params={"return_to": "https://example.org/steal"}
    )

    assert started.status_code == 422
    assert "x_sign_in_browser" not in sign_in_browser.cookies


@pytest.mark.parametrize(
    "return_to",
    [
        "//example.org/oauth/consent?request=one",
        "/new",
        "/oauth/consent",
        "/oauth/consent?request=one#https://example.org",
        "/oauth/consent?request=one\\evil",
        "/oauth/consent?request=one\r\nLocation: https://example.org",
    ],
)
async def test_only_a_pending_internal_consent_path_can_be_a_return_destination(
    sign_in_browser, return_to
):
    response = await sign_in_browser.get("/api/v1/login/x", params={"return_to": return_to})

    assert response.status_code == 422
    assert "x_sign_in_browser" not in sign_in_browser.cookies


async def test_a_pending_consent_return_can_be_kept_without_being_sent_to_x(sign_in_browser):
    destination = "/oauth/consent?request=request_one"

    started = await sign_in_browser.get("/api/v1/login/x", params={"return_to": destination})

    assert started.status_code == 200
    assert destination not in started.json()["url"]
    assert "return_to" not in parse_qs(urlsplit(started.json()["url"]).query)


@pytest.mark.parametrize(
    "public_url,secure", [("https://pumpkit.example", True), ("http://localhost:5173", False)]
)
async def test_the_browser_binding_is_an_expiring_http_only_cookie(
    sign_in_browser, monkeypatch, public_url, secure
):
    monkeypatch.setattr(settings, "PUBLIC_URL", public_url)

    started = await sign_in_browser.get("/api/v1/login/x")

    cookie = started.headers["set-cookie"]
    assert cookie.startswith("x_sign_in_browser=")
    assert "; HttpOnly" in cookie
    assert "; Max-Age=600" in cookie
    assert "; Path=/" in cookie
    assert "; SameSite=lax" in cookie
    assert ("; Secure" in cookie) is secure
    query = parse_qs(urlsplit(started.json()["url"]).query)
    secret = started.cookies["x_sign_in_browser"]
    assert len(secret) >= 43
    assert secret not in (query["state"][0], query["code_challenge"][0])
    assert secret not in started.json()["url"]


async def test_each_attempt_gets_fresh_state_pkce_and_browser_binding(sign_in_browser):
    first = await sign_in_browser.get("/api/v1/login/x")
    second = await sign_in_browser.get("/api/v1/login/x")

    first_query = parse_qs(urlsplit(first.json()["url"]).query)
    second_query = parse_qs(urlsplit(second.json()["url"]).query)
    assert first_query["state"] != second_query["state"]
    assert first_query["code_challenge"] != second_query["code_challenge"]
    assert first.cookies["x_sign_in_browser"] != second.cookies["x_sign_in_browser"]


async def test_the_x_callback_is_derived_from_the_instance_configuration(
    sign_in_app, sign_in_browser, monkeypatch
):
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://pumpkit.example")
    monkeypatch.setattr(settings, "X_CLIENT_ID", "throwaway-x-client")
    monkeypatch.setattr(settings, "X_CLIENT_SECRET", "throwaway-x-secret")
    sign_in_app.dependency_overrides[get_x_publisher] = OfficialXPublisher

    started = await sign_in_browser.get("/api/v1/login/x")

    query = parse_qs(urlsplit(started.json()["url"]).query)
    assert query["client_id"] == ["throwaway-x-client"]
    assert query["redirect_uri"] == ["https://pumpkit.example/oauth/x/callback"]
    assert query["code_challenge_method"] == ["S256"]


@pytest.mark.parametrize("identity", [{"email": "victim@example.com"}, {"x_user_id": "1234"}])
async def test_browser_supplied_identity_is_not_accepted(sign_in_browser, identity):
    started = await sign_in_browser.get("/api/v1/login/x", params=identity)

    assert started.status_code == 422
    assert "x_sign_in_browser" not in sign_in_browser.cookies


async def test_sign_in_initiation_is_rate_limited_without_issuing_a_session(sign_in_browser):
    for _ in range(10):
        assert (await sign_in_browser.get("/api/v1/login/x")).status_code == 200

    limited = await sign_in_browser.get("/api/v1/login/x")

    assert limited.status_code == 429
    assert "refresh_token" not in sign_in_browser.cookies


async def test_prepared_sign_in_is_not_mounted_in_the_production_app(new_browser):
    response = await new_browser().get("/api/v1/login/x")

    assert response.status_code == 404
    assert "x_sign_in_browser" not in response.cookies
