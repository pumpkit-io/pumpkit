"""
The Sign-up allowlist over HTTP: who may sign in by Magic link and by Google.
"""

import pytest
from sqlalchemy import select

from pumpkit.auth.google_sign_in import GoogleClaims
from pumpkit.auth.models import User
from pumpkit.core.config import settings
from tests.conftest import magic_link_token

EMAIL_NOT_ALLOWED = "http://localhost:5173/login?error=email_not_allowed"
CALLBACK = "http://localhost:5173/auth/magic-link/callback#"


@pytest.fixture
def allowlist(monkeypatch):
    def _set(value: str) -> None:
        monkeypatch.setattr(settings, "SIGN_UP_ALLOWLIST", value)

    return _set


async def test_a_magic_link_request_for_an_address_not_on_the_list_is_refused_and_sends_nothing(
    new_browser, auth_outbox, allowlist
):
    allowlist("alice@example.com, @team.example")

    response = await new_browser().post(
        "/api/v1/login/magic-link/request", json={"email": "mallory@example.com"}
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "email_not_allowed"}
    assert auth_outbox.messages == []


@pytest.mark.parametrize(
    "email", ["alice@example.com", "Alice@Example.com", "bob@team.example", "BOB@TEAM.EXAMPLE"]
)
async def test_an_address_on_the_list_or_in_a_listed_domain_signs_in_by_magic_link(
    new_browser, auth_outbox, allowlist, email
):
    allowlist("alice@example.com, @team.example")
    browser = new_browser()

    requested = await browser.post("/api/v1/login/magic-link/request", json={"email": email})
    opened = await browser.get(
        "/api/v1/login/magic-link",
        params={"token": magic_link_token(auth_outbox.messages[-1].link_url)},
    )

    assert requested.status_code == 200
    assert opened.headers["location"].startswith(CALLBACK)
    assert "refresh_token" in browser.cookies


async def test_a_magic_link_sent_before_the_address_was_removed_is_refused_at_completion(
    new_browser, auth_outbox, allowlist
):
    allowlist("bob@example.com")
    browser = new_browser()
    await browser.post("/api/v1/login/magic-link/request", json={"email": "bob@example.com"})
    token = magic_link_token(auth_outbox.messages[-1].link_url)

    allowlist("alice@example.com")
    opened = await browser.get("/api/v1/login/magic-link", params={"token": token})

    assert opened.status_code == 303
    assert opened.headers["location"] == EMAIL_NOT_ALLOWED
    assert "refresh_token" not in browser.cookies


@pytest.mark.parametrize("email", ["Alice@Example.com", "bob@team.example"])
async def test_an_address_on_the_list_or_in_a_listed_domain_signs_in_with_google(
    new_browser, sign_in_with_google, allowlist, email
):
    allowlist("alice@example.com, @team.example")
    browser = new_browser()

    landed = await sign_in_with_google(browser, GoogleClaims(subject="google-sub", email=email))

    assert landed.headers["location"].startswith("http://localhost:5173/oauth/google/callback#")
    assert "refresh_token" in browser.cookies


async def test_google_sign_in_for_an_address_not_on_the_list_is_refused(
    new_browser, sign_in_with_google, allowlist, db
):
    allowlist("alice@example.com, @team.example")
    browser = new_browser()

    landed = await sign_in_with_google(
        browser, GoogleClaims(subject="google-sub-mallory", email="mallory@example.com")
    )

    assert landed.status_code == 303
    assert landed.headers["location"] == EMAIL_NOT_ALLOWED
    assert "refresh_token" not in browser.cookies
    mallory = await db.scalar(select(User).where(User.email == "mallory@example.com"))
    assert mallory is None


async def test_an_empty_list_lets_anyone_sign_in(
    new_browser, sign_in_by_magic_link, sign_in_with_google, allowlist
):
    allowlist("")

    await sign_in_by_magic_link(new_browser(), "anyone@example.com")
    landed = await sign_in_with_google(
        new_browser(), GoogleClaims(subject="google-sub-other", email="other@elsewhere.example")
    )

    assert landed.headers["location"].startswith("http://localhost:5173/oauth/google/callback#")


async def test_an_open_session_still_refreshes_after_the_address_is_removed(
    new_browser, sign_in_by_magic_link, allowlist
):
    allowlist("bob@example.com")
    browser = new_browser()
    await sign_in_by_magic_link(browser, "bob@example.com")

    allowlist("alice@example.com")
    refreshed = await browser.post("/api/v1/refresh-token")

    assert refreshed.status_code == 200
