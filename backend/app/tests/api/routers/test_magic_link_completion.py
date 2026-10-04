"""
Magic link completion over HTTP: a link signs a browser in once, and every
rejected link lands on the sign-in page with `invalid_magic_link` and no cookie.
"""

import asyncio
from datetime import timedelta

from httpx import AsyncClient, Response

from app.tests.conftest import magic_link_token

INVALID_MAGIC_LINK = "http://localhost:5173/login?error=invalid_magic_link"
CALLBACK = "http://localhost:5173/auth/magic-link/callback#"


async def _request_link(browser: AsyncClient, auth_outbox, email: str = "bob@example.com") -> str:
    requested = await browser.post("/api/v1/login/magic-link/request", json={"email": email})
    assert requested.status_code == 200
    return magic_link_token(auth_outbox.messages[-1].link_url)


async def _open(browser: AsyncClient, token: str) -> Response:
    return await browser.get("/api/v1/login/magic-link", params={"token": token})


def _assert_rejected(response: Response, browser: AsyncClient) -> None:
    assert response.status_code == 303
    assert response.headers["location"] == INVALID_MAGIC_LINK
    assert "set-cookie" not in response.headers
    assert "refresh_token" not in browser.cookies


async def test_unknown_link_is_rejected(new_browser):
    browser = new_browser()

    _assert_rejected(await _open(browser, "not-a-real-token"), browser)


async def test_used_link_is_rejected(new_browser, auth_outbox):
    token = await _request_link(new_browser(), auth_outbox)
    assert (await _open(new_browser(), token)).headers["location"].startswith(CALLBACK)

    replaying = new_browser()
    _assert_rejected(await _open(replaying, token), replaying)


async def test_expired_link_is_rejected(new_browser, auth_outbox, clock):
    browser = new_browser()
    token = await _request_link(browser, auth_outbox)

    clock.advance(timedelta(minutes=15))

    _assert_rejected(await _open(browser, token), browser)


async def test_link_opened_just_before_expiry_signs_in(new_browser, auth_outbox, clock):
    browser = new_browser()
    token = await _request_link(browser, auth_outbox)

    clock.advance(timedelta(minutes=14, seconds=59))

    opened = await _open(browser, token)
    assert opened.headers["location"].startswith(CALLBACK)
    assert "refresh_token" in browser.cookies


async def test_two_concurrent_completions_start_exactly_one_session(new_browser, auth_outbox):
    token = await _request_link(new_browser(), auth_outbox)
    first, second = new_browser(), new_browser()

    responses = await asyncio.gather(_open(first, token), _open(second, token))

    locations = sorted(response.headers["location"] for response in responses)
    assert locations[0].startswith(CALLBACK)
    assert locations[1] == INVALID_MAGIC_LINK
    signed_in = [b for b in (first, second) if "refresh_token" in b.cookies]
    assert len(signed_in) == 1
    assert (await signed_in[0].post("/api/v1/refresh-token")).status_code == 200


async def test_new_link_after_the_cooldown_invalidates_the_earlier_one(
    new_browser, auth_outbox, clock
):
    browser = new_browser()
    earlier = await _request_link(browser, auth_outbox)
    clock.advance(timedelta(seconds=61))
    later = await _request_link(browser, auth_outbox)
    assert len(auth_outbox.messages) == 2

    _assert_rejected(await _open(browser, earlier), browser)
    opened = await _open(browser, later)
    assert opened.headers["location"].startswith(CALLBACK)
    assert "refresh_token" in browser.cookies


async def test_request_within_the_cooldown_sends_no_new_link(new_browser, auth_outbox, clock):
    browser = new_browser()
    token = await _request_link(browser, auth_outbox)
    clock.advance(timedelta(seconds=59))

    second = await browser.post(
        "/api/v1/login/magic-link/request", json={"email": "bob@example.com"}
    )

    assert second.status_code == 200
    assert len(auth_outbox.messages) == 1
    assert (await _open(browser, token)).headers["location"].startswith(CALLBACK)
