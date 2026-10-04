"""
Google sign-in over HTTP, through the fake `GoogleSignIn` port and real token verification.
"""

from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

from httpx import AsyncClient, Response
from sqlalchemy import func, select

import app.api.services.sessions as sessions
from app.core.google_sign_in import GoogleClaims
from app.db.models import GoogleIdentity, User
from app.tests.conftest import callback_fragment

SIGN_IN_FAILED = "http://localhost:5173/login?error=sign_in_failed"

ALICE_GOOGLE = GoogleClaims(
    subject="google-sub-alice",
    email="alice@example.com",
    given_name="Alice",
    family_name="Liddell",
    name="Alice Liddell",
)


async def _profile(browser: AsyncClient, landed: Response) -> dict:
    """The profile of the User the callback redirect signed in, read with its access token."""
    access_token = callback_fragment(landed.headers["location"])["access_token"]
    me = await browser.get("/api/v1/users/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me.status_code == 200
    return me.json()


async def test_first_google_sign_in_creates_the_user_and_starts_a_session(
    new_browser, sign_in_with_google
):
    browser = new_browser()

    landed = await sign_in_with_google(browser, ALICE_GOOGLE)

    assert landed.status_code == 303
    assert landed.headers["location"].startswith("http://localhost:5173/oauth/google/callback#")
    assert "refresh_token" in browser.cookies
    profile = await _profile(browser, landed)
    assert profile["email"] == "alice@example.com"
    assert profile["first_name"] == "Alice"
    assert profile["last_name"] == "Liddell"


async def test_a_later_google_sign_in_with_the_same_subject_reaches_the_same_user(
    new_browser, sign_in_with_google
):
    await sign_in_with_google(new_browser(), ALICE_GOOGLE)
    # Same Google account, whose email has changed since: the subject decides.
    renamed = replace(ALICE_GOOGLE, email="alice.new@example.com")

    browser = new_browser()
    landed = await sign_in_with_google(browser, renamed)

    assert landed.status_code == 303
    assert (await _profile(browser, landed))["email"] == "alice@example.com"


async def test_google_sign_in_for_a_magic_link_users_email_links_to_that_user(
    new_browser, sign_in_by_magic_link, sign_in_with_google, user
):
    await sign_in_by_magic_link(new_browser(), user.email)
    # Google may report the address with different casing.
    alice_by_google = replace(ALICE_GOOGLE, email="Alice@Example.com")

    linked = await sign_in_with_google(new_browser(), alice_by_google)
    assert linked.status_code == 303
    # The Google account is now linked to Alice: it keeps reaching her under another email.
    browser = new_browser()
    later = await sign_in_with_google(browser, replace(alice_by_google, email="a@example.org"))

    profile = await _profile(browser, later)
    assert profile["email"] == "alice@example.com"
    # Alice had no first or last name yet: Google's names fill them in.
    assert profile["first_name"] == "Alice"
    assert profile["last_name"] == "Liddell"


async def test_a_failed_google_code_exchange_lands_on_login_with_sign_in_failed(
    new_browser, sign_in_with_google, fake_google, fake_posthog
):
    fake_google.fail = True
    browser = new_browser()

    landed = await sign_in_with_google(browser, ALICE_GOOGLE)

    assert landed.status_code == 303
    assert landed.headers["location"] == SIGN_IN_FAILED
    assert "refresh_token" not in browser.cookies
    # An expected failure is not an error to report.
    fake_posthog.capture_exception.assert_not_called()


async def test_a_cancelled_google_consent_lands_on_login_with_sign_in_failed(new_browser):
    browser = new_browser()
    started = await browser.get("/api/v1/login/google")
    assert started.status_code == 200

    landed = await browser.get(
        "/api/v1/oauth/google/callback", params={"error": "access_denied", "state": "whatever"}
    )

    assert landed.status_code == 303
    assert landed.headers["location"] == SIGN_IN_FAILED


async def test_a_google_callback_with_another_browsers_state_lands_on_login_with_sign_in_failed(
    new_browser, fake_google
):
    fake_google.claims = ALICE_GOOGLE
    started = await new_browser().get("/api/v1/login/google")
    state = parse_qs(urlsplit(started.json()["url"]).query)["state"][0]

    browser = new_browser()
    await browser.get("/api/v1/login/google")
    landed = await browser.get(
        "/api/v1/oauth/google/callback", params={"code": "auth-code", "state": state}
    )

    assert landed.status_code == 303
    assert landed.headers["location"] == SIGN_IN_FAILED
    assert "refresh_token" not in browser.cookies


async def test_a_suspended_user_signing_in_with_google_lands_on_login_without_a_session(
    new_browser, sign_in_with_google, suspend_user
):
    await sign_in_with_google(new_browser(), ALICE_GOOGLE)
    await suspend_user(ALICE_GOOGLE.email)
    browser = new_browser()

    landed = await sign_in_with_google(browser, ALICE_GOOGLE)

    assert landed.status_code == 303
    assert landed.headers["location"] == "http://localhost:5173/login?error=account_suspended"
    assert "refresh_token" not in browser.cookies


async def test_a_failure_before_the_session_starts_is_reported_and_leaves_no_partial_user(
    new_browser, sign_in_with_google, monkeypatch, fake_posthog, db
):
    async def _session_start_breaks(*_args, **_kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(sessions, "start", _session_start_breaks)
    browser = new_browser()

    landed = await sign_in_with_google(browser, ALICE_GOOGLE)

    assert landed.status_code == 303
    assert landed.headers["location"] == SIGN_IN_FAILED
    assert "refresh_token" not in browser.cookies
    fake_posthog.capture_exception.assert_called_once()
    # The User and Google identity were created in the same transaction: both rolled back.
    assert (await db.execute(select(func.count()).select_from(User))).scalar_one() == 0
    assert (await db.execute(select(func.count()).select_from(GoogleIdentity))).scalar_one() == 0
