"""
A Suspended User can't sign in or keep a Session, over HTTP with real token verification.
"""

from app.tests.api.routers.test_magic_link_request import GENERIC_MESSAGE
from app.tests.conftest import magic_link_token


async def test_suspended_user_completing_a_magic_link_lands_on_the_sign_in_page_without_a_session(
    new_browser, auth_outbox, suspend_user, user
):
    await suspend_user(user.email)
    browser = new_browser()
    requested = await browser.post("/api/v1/login/magic-link/request", json={"email": user.email})
    assert requested.status_code == 200

    opened = await browser.get(
        "/api/v1/login/magic-link",
        params={"token": magic_link_token(auth_outbox.messages[-1].link_url)},
    )

    assert opened.status_code == 303
    assert opened.headers["location"] == "http://localhost:5173/login?error=account_suspended"
    assert "refresh_token" not in browser.cookies
    assert "set-cookie" not in opened.headers


async def test_a_magic_link_refused_for_suspension_stays_used(
    new_browser, auth_outbox, suspend_user, lift_suspension, user
):
    await suspend_user(user.email)
    browser = new_browser()
    await browser.post("/api/v1/login/magic-link/request", json={"email": user.email})
    token = magic_link_token(auth_outbox.messages[-1].link_url)
    refused = await browser.get("/api/v1/login/magic-link", params={"token": token})
    assert refused.headers["location"] == "http://localhost:5173/login?error=account_suspended"

    await lift_suspension(user.email)
    reopened = await browser.get("/api/v1/login/magic-link", params={"token": token})

    assert reopened.headers["location"] == "http://localhost:5173/login?error=invalid_magic_link"


async def test_suspending_a_signed_in_user_refuses_their_refresh_and_revokes_all_sessions(
    new_browser, sign_in_by_magic_link, suspend_user, lift_suspension, user
):
    browser = new_browser()
    other_browser = new_browser()
    await sign_in_by_magic_link(browser, user.email)
    await sign_in_by_magic_link(other_browser, user.email)

    await suspend_user(user.email)
    refused = await browser.post("/api/v1/refresh-token")

    assert refused.status_code == 401
    assert refused.headers["WWW-Authenticate"] == "Bearer"
    assert refused.json() == {"detail": "account_suspended"}

    # Lifting the suspension doesn't bring the revoked Sessions back: sign in again.
    await lift_suspension(user.email)
    assert (await browser.post("/api/v1/refresh-token")).status_code == 401
    assert (await other_browser.post("/api/v1/refresh-token")).status_code == 401

    await sign_in_by_magic_link(browser, user.email)
    assert (await browser.post("/api/v1/refresh-token")).status_code == 200


async def test_a_suspended_user_replaying_a_rotated_refresh_token_is_refused_as_suspended(
    new_browser, sign_in_by_magic_link, suspend_user, lift_suspension, user
):
    browser = new_browser()
    other_browser = new_browser()
    await sign_in_by_magic_link(browser, user.email)
    await sign_in_by_magic_link(other_browser, user.email)
    rotated_away = browser.cookies["refresh_token"]
    assert (await browser.post("/api/v1/refresh-token")).status_code == 200

    await suspend_user(user.email)
    browser.cookies.set("refresh_token", rotated_away)
    refused = await browser.post("/api/v1/refresh-token")

    assert refused.status_code == 401
    assert refused.json() == {"detail": "account_suspended"}
    # Suspension revokes every Session, not only the replayed one.
    await lift_suspension(user.email)
    assert (await other_browser.post("/api/v1/refresh-token")).status_code == 401


async def test_suspended_users_still_valid_access_token_is_refused(
    authed_client, suspend_user, user
):
    assert (await authed_client.get("/api/v1/users/me")).status_code == 200

    await suspend_user(user.email)
    refused = await authed_client.get("/api/v1/users/me")

    assert refused.status_code == 401
    assert refused.headers["WWW-Authenticate"] == "Bearer"


async def test_requesting_a_magic_link_for_a_suspended_user_gets_the_generic_response(
    new_browser, suspend_user, user
):
    await suspend_user(user.email)
    browser = new_browser()

    for_suspended = await browser.post(
        "/api/v1/login/magic-link/request", json={"email": user.email}
    )
    for_unknown = await browser.post(
        "/api/v1/login/magic-link/request", json={"email": "nobody@example.com"}
    )

    assert for_suspended.status_code == for_unknown.status_code == 200
    assert for_suspended.json() == for_unknown.json() == {"message": GENERIC_MESSAGE}


async def test_other_magic_link_failures_still_redirect_with_invalid_magic_link(new_browser):
    opened = await new_browser().get("/api/v1/login/magic-link", params={"token": "unknown"})

    assert opened.status_code == 303
    assert opened.headers["location"] == "http://localhost:5173/login?error=invalid_magic_link"
