from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from test_complete import begin, complete, profile

from pumpkit.x_connection.x_publisher import X_SIGN_IN_SCOPES, XPublisherError

PHOTO_URL = "https://pbs.twimg.com/profile_images/ada.jpg"
PHOTO = "data:image/jpeg;base64,eA=="


async def test_x_sign_in_uses_x_photo_and_read_only_handle(
    sign_in_browser, fake_x_publisher, fake_photo_fetcher
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    fake_x_publisher.account = replace(fake_x_publisher.account, photo_url=PHOTO_URL)
    fake_photo_fetcher.photos[PHOTO_URL] = PHOTO

    me = await profile(
        sign_in_browser, await complete(sign_in_browser, await begin(sign_in_browser))
    )

    assert me["avatar_data_url"] == PHOTO
    assert me["x_handle"] == "ada"


@pytest.mark.parametrize("override", [None, PHOTO])
async def test_x_profile_refuses_photo_overrides(sign_in_browser, fake_x_publisher, override):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    issued = await complete(sign_in_browser, await begin(sign_in_browser))
    headers = {"Authorization": f"Bearer {issued.json()['access_token']}"}

    rejected = await sign_in_browser.patch(
        "/api/v1/users/me", json={"avatar_data_url": override}, headers=headers
    )

    assert rejected.status_code == 403
    me = await sign_in_browser.get("/api/v1/users/me", headers=headers)
    assert me.json()["avatar_data_url"] is None


@pytest.mark.parametrize("field", ["email", "x_handle", "x_user_id"])
async def test_profile_identity_cannot_be_overridden(sign_in_browser, fake_x_publisher, field):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    issued = await complete(sign_in_browser, await begin(sign_in_browser))

    rejected = await sign_in_browser.patch(
        "/api/v1/users/me",
        json={field: "somebody-else"},
        headers={"Authorization": f"Bearer {issued.json()['access_token']}"},
    )

    assert rejected.status_code == 422


async def test_x_photo_changes_and_removal_follow_successful_sign_ins(
    sign_in_browser, fake_x_publisher, fake_photo_fetcher
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    fake_x_publisher.account = replace(fake_x_publisher.account, photo_url=PHOTO_URL)
    fake_photo_fetcher.photos[PHOTO_URL] = PHOTO
    await complete(sign_in_browser, await begin(sign_in_browser))
    other_url = "https://pbs.twimg.com/profile_images/new.jpg"
    other_photo = "data:image/jpeg;base64,eQ=="
    fake_x_publisher.account = replace(fake_x_publisher.account, photo_url=other_url)
    fake_photo_fetcher.photos[other_url] = other_photo

    changed = await profile(
        sign_in_browser, await complete(sign_in_browser, await begin(sign_in_browser))
    )
    assert changed["avatar_data_url"] == other_photo

    fake_x_publisher.account = replace(fake_x_publisher.account, photo_url=None)
    removed = await profile(
        sign_in_browser, await complete(sign_in_browser, await begin(sign_in_browser))
    )
    assert removed["avatar_data_url"] is None


async def test_failed_image_download_keeps_photo_and_retries_at_next_sign_in(
    sign_in_browser, fake_x_publisher, fake_photo_fetcher
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    fake_x_publisher.account = replace(fake_x_publisher.account, photo_url=PHOTO_URL)
    fake_photo_fetcher.photos[PHOTO_URL] = PHOTO
    await complete(sign_in_browser, await begin(sign_in_browser))
    other_url = "https://pbs.twimg.com/profile_images/new.jpg"
    fake_x_publisher.account = replace(fake_x_publisher.account, photo_url=other_url)

    failed_image = await profile(
        sign_in_browser, await complete(sign_in_browser, await begin(sign_in_browser))
    )
    assert failed_image["avatar_data_url"] == PHOTO

    fake_photo_fetcher.photos[other_url] = "data:image/jpeg;base64,eQ=="
    retried = await profile(
        sign_in_browser, await complete(sign_in_browser, await begin(sign_in_browser))
    )
    assert retried["avatar_data_url"] == "data:image/jpeg;base64,eQ=="


async def test_failed_x_profile_fetch_does_not_remove_the_stored_photo(
    sign_in_browser, fake_x_publisher, fake_photo_fetcher
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    fake_x_publisher.account = replace(fake_x_publisher.account, photo_url=PHOTO_URL)
    fake_photo_fetcher.photos[PHOTO_URL] = PHOTO
    issued = await complete(sign_in_browser, await begin(sign_in_browser))
    fake_x_publisher.fail_fetch_account = XPublisherError("unavailable")

    failed = await complete(sign_in_browser, await begin(sign_in_browser))
    assert failed.status_code == 502
    me = await sign_in_browser.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {issued.json()['access_token']}"}
    )
    assert me.json()["avatar_data_url"] == PHOTO


async def test_ordinary_profile_reads_do_not_fetch_x_or_its_photo(
    sign_in_browser, fake_x_publisher, fake_photo_fetcher
):
    fake_x_publisher.exchange_scope = X_SIGN_IN_SCOPES
    spy = AsyncMock(wraps=fake_x_publisher.fetch_account)
    fake_x_publisher.fetch_account = spy
    issued = await complete(sign_in_browser, await begin(sign_in_browser))

    await profile(sign_in_browser, issued)
    await profile(sign_in_browser, issued)

    assert spy.await_count == 1
    assert fake_photo_fetcher.fetched == []
