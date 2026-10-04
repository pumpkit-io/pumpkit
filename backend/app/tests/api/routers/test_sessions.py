"""
Sessions over HTTP: Magic link sign-in starts one, `/refresh-token` rotates it and
`/logout` ends it. Browsers come from `new_browser`, so real token verification runs.
"""

import jwt

from app.tests.conftest import callback_fragment, magic_link_token


def _subject(access_token: str) -> str:
    return jwt.decode(access_token, options={"verify_signature": False})["sub"]


async def test_magic_link_sign_in_refresh_and_logout_journey(new_browser, auth_outbox):
    browser = new_browser()

    requested = await browser.post(
        "/api/v1/login/magic-link/request", json={"email": "bob@example.com"}
    )
    assert requested.status_code == 200
    [message] = auth_outbox.messages

    opened = await browser.get(
        "/api/v1/login/magic-link", params={"token": magic_link_token(message.link_url)}
    )
    assert opened.status_code == 303
    location = opened.headers["location"]
    assert location.startswith("http://localhost:5173/auth/magic-link/callback#")
    fragment = callback_fragment(location)
    assert fragment["token_type"] == "Bearer"
    assert fragment["expires_at"]
    first_cookie = browser.cookies["refresh_token"]

    claims = jwt.decode(fragment["access_token"], options={"verify_signature": False})
    assert claims["sub"].startswith("user")
    assert "email" not in claims

    me = await browser.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {fragment['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "bob@example.com"

    refreshed = await browser.post("/api/v1/refresh-token")
    assert refreshed.status_code == 200
    assert refreshed.json()["token_type"] == "Bearer"
    rotated_cookie = browser.cookies["refresh_token"]
    assert rotated_cookie != first_cookie
    refreshed_me = await browser.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {refreshed.json()['access_token']}"},
    )
    assert refreshed_me.status_code == 200

    logged_out = await browser.post("/api/v1/logout")
    assert logged_out.status_code == 200
    assert logged_out.json() == {"message": "Logged out successfully"}
    assert "refresh_token" not in browser.cookies

    browser.cookies.set("refresh_token", rotated_cookie)
    after_logout = await browser.post("/api/v1/refresh-token")
    assert after_logout.status_code == 401


async def test_reusing_a_rotated_refresh_token_revokes_only_that_session(
    new_browser, sign_in_by_magic_link, user
):
    browser = new_browser()
    other_browser = new_browser()
    await sign_in_by_magic_link(browser, user.email)
    await sign_in_by_magic_link(other_browser, user.email)

    stolen_cookie = browser.cookies["refresh_token"]
    assert (await browser.post("/api/v1/refresh-token")).status_code == 200
    rotated_cookie = browser.cookies["refresh_token"]

    browser.cookies.set("refresh_token", stolen_cookie)
    replayed = await browser.post("/api/v1/refresh-token")
    assert replayed.status_code == 401
    assert replayed.headers["WWW-Authenticate"] == "Bearer"
    assert replayed.json() == {"detail": "invalid_refresh_token"}

    # The replay revoked the whole Session, so its newest token stops working too.
    browser.cookies.set("refresh_token", rotated_cookie)
    assert (await browser.post("/api/v1/refresh-token")).status_code == 401

    assert (await other_browser.post("/api/v1/refresh-token")).status_code == 200


async def test_logout_ends_only_the_session_in_this_browser(
    new_browser, sign_in_by_magic_link, user
):
    browser = new_browser()
    other_browser = new_browser()
    await sign_in_by_magic_link(browser, user.email)
    await sign_in_by_magic_link(other_browser, user.email)
    signed_out_cookie = browser.cookies["refresh_token"]

    assert (await browser.post("/api/v1/logout")).status_code == 200

    browser.cookies.set("refresh_token", signed_out_cookie)
    assert (await browser.post("/api/v1/refresh-token")).status_code == 401
    assert (await other_browser.post("/api/v1/refresh-token")).status_code == 200


async def test_first_magic_link_sign_in_creates_the_user_and_the_next_reaches_the_same_user(
    new_browser, sign_in_by_magic_link
):
    first = await sign_in_by_magic_link(new_browser(), "carol@example.com")
    second = await sign_in_by_magic_link(new_browser(), "carol@example.com")

    renamed = await new_browser().patch(
        "/api/v1/users/me",
        json={"first_name": "Carol"},
        headers={"Authorization": f"Bearer {first.access_token}"},
    )
    assert renamed.status_code == 200

    me = await new_browser().get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {second.access_token}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "carol@example.com"
    assert me.json()["first_name"] == "Carol"
    assert _subject(first.access_token) == _subject(second.access_token)


async def test_authed_client_reaches_protected_endpoints_as_the_user(authed_client):
    me = await authed_client.get("/api/v1/users/me")

    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"


async def test_refresh_without_a_cookie_is_refused(new_browser):
    response = await new_browser().post("/api/v1/refresh-token")

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_refresh_token"}
