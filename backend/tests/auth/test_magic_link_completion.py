"""
Magic link completion over HTTP: a link signs a browser in once, and every
rejected link lands on the sign-in page with `invalid_magic_link` and no cookie.
"""

import asyncio
from datetime import timedelta
from typing import Optional

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select

from pumpkit.auth.models import RefreshToken
from pumpkit.core.config import settings
from tests.conftest import callback_fragment, magic_link_token

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


BOB_GRAVATAR = (
    "https://gravatar.com/avatar/"
    "5ff860bf1190596c7188ab851db691f0f3169c453936e9e1eba2f9a47f7a0018?s=256&d=404"
)
GRAVATAR_PHOTO = "data:image/jpeg;base64,R3JhdmF0YXJQaG90bw=="
UPLOADED_PHOTO = "data:image/jpeg;base64,VXBsb2FkZWRQaG90bw=="


@pytest.fixture
def gravatar_on(monkeypatch):
    monkeypatch.setattr(settings, "GRAVATAR_ENABLED", True)


async def _sign_in(browser: AsyncClient, auth_outbox, clock, email: str = "bob@example.com") -> str:
    """Complete a fresh Magic link and return the access token it signed in with."""
    clock.advance(timedelta(seconds=61))
    opened = await _open(browser, await _request_link(browser, auth_outbox, email))
    assert opened.headers["location"].startswith(CALLBACK)
    return callback_fragment(opened.headers["location"])["access_token"]


async def _photo(browser: AsyncClient, access_token: str) -> Optional[str]:
    me = await browser.get("/api/v1/users/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me.status_code == 200
    return me.json()["avatar_data_url"]


async def _set_photo(browser: AsyncClient, access_token: str, photo: Optional[str]) -> None:
    saved = await browser.patch(
        "/api/v1/users/me",
        json={"avatar_data_url": photo},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert saved.status_code == 200


@pytest.mark.usefixtures("gravatar_on")
async def test_with_gravatar_on_a_first_magic_link_makes_the_gravatar_the_photo(
    new_browser, auth_outbox, clock, fake_photo_fetcher
):
    fake_photo_fetcher.photos[BOB_GRAVATAR] = GRAVATAR_PHOTO
    browser = new_browser()

    access_token = await _sign_in(browser, auth_outbox, clock, " Bob@Example.com ")

    assert await _photo(browser, access_token) == GRAVATAR_PHOTO


async def test_with_gravatar_off_a_magic_link_never_asks_for_a_photo(
    new_browser, auth_outbox, clock, fake_photo_fetcher
):
    fake_photo_fetcher.photos[BOB_GRAVATAR] = GRAVATAR_PHOTO
    browser = new_browser()

    access_token = await _sign_in(browser, auth_outbox, clock)

    assert await _photo(browser, access_token) is None
    assert fake_photo_fetcher.fetched == []


@pytest.mark.usefixtures("gravatar_on")
async def test_an_email_without_a_gravatar_signs_in_with_no_photo(
    new_browser, auth_outbox, clock, fake_photo_fetcher
):
    browser = new_browser()

    access_token = await _sign_in(browser, auth_outbox, clock)

    assert await _photo(browser, access_token) is None
    assert fake_photo_fetcher.fetched == [BOB_GRAVATAR]


@pytest.mark.usefixtures("gravatar_on")
async def test_a_failed_gravatar_download_still_signs_in_and_the_next_magic_link_fills_the_photo(
    new_browser, auth_outbox, clock, fake_photo_fetcher
):
    browser = new_browser()
    failed = await _sign_in(browser, auth_outbox, clock)
    assert await _photo(browser, failed) is None

    fake_photo_fetcher.photos[BOB_GRAVATAR] = GRAVATAR_PHOTO
    later = await _sign_in(browser, auth_outbox, clock)

    assert await _photo(browser, later) == GRAVATAR_PHOTO


@pytest.mark.usefixtures("gravatar_on")
async def test_a_magic_link_keeps_an_uploaded_photo(
    new_browser, auth_outbox, clock, fake_photo_fetcher
):
    browser = new_browser()
    await _set_photo(browser, await _sign_in(browser, auth_outbox, clock), UPLOADED_PHOTO)
    fake_photo_fetcher.photos[BOB_GRAVATAR] = GRAVATAR_PHOTO

    access_token = await _sign_in(browser, auth_outbox, clock)

    assert await _photo(browser, access_token) == UPLOADED_PHOTO


@pytest.mark.usefixtures("gravatar_on")
async def test_a_magic_link_never_fills_a_photo_the_user_cleared(
    new_browser, auth_outbox, clock, fake_photo_fetcher
):
    fake_photo_fetcher.photos[BOB_GRAVATAR] = GRAVATAR_PHOTO
    browser = new_browser()
    await _set_photo(browser, await _sign_in(browser, auth_outbox, clock), None)

    access_token = await _sign_in(browser, auth_outbox, clock)

    assert await _photo(browser, access_token) is None


@pytest.mark.usefixtures("gravatar_on")
async def test_the_sign_in_is_committed_before_the_gravatar_downloads(
    new_browser, auth_outbox, clock, fake_photo_fetcher, db_session_maker, monkeypatch
):
    sessions_seen_while_downloading: list[int] = []
    download = fake_photo_fetcher.fetch

    async def download_after_looking(url: str) -> Optional[str]:
        # An independent connection sees only what the sign-in has committed.
        async with db_session_maker() as other:
            committed = select(func.count()).select_from(RefreshToken)
            sessions_seen_while_downloading.append((await other.execute(committed)).scalar_one())
        return await download(url)

    monkeypatch.setattr(fake_photo_fetcher, "fetch", download_after_looking)
    fake_photo_fetcher.photos[BOB_GRAVATAR] = GRAVATAR_PHOTO
    browser = new_browser()

    access_token = await _sign_in(browser, auth_outbox, clock)

    assert sessions_seen_while_downloading == [1]
    assert await _photo(browser, access_token) == GRAVATAR_PHOTO


@pytest.mark.usefixtures("gravatar_on")
async def test_a_gravatar_that_fails_to_save_still_signs_in(
    new_browser, auth_outbox, clock, fake_photo_fetcher, monkeypatch
):
    async def broken_download(url: str) -> Optional[str]:
        raise RuntimeError("the photo port broke its promise")

    monkeypatch.setattr(fake_photo_fetcher, "fetch", broken_download)
    browser = new_browser()

    access_token = await _sign_in(browser, auth_outbox, clock)

    assert await _photo(browser, access_token) is None
