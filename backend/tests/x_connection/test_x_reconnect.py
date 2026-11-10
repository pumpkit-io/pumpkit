from dataclasses import replace
from datetime import timedelta
from io import StringIO
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from pumpkit.account_deletion import run_cli
from pumpkit.x_connection.models import XConnection
from pumpkit.x_connection.x_publisher import XPublisherError, XReconnectNeededError


@pytest.fixture
async def x_identity(db, user):
    user.x_user_id = "1001"
    user.x_handle = "ada"
    await db.commit()
    return user


async def authorize(client):
    started = await client.post("/api/v1/x-connection/authorizations")
    assert started.status_code == 200, started.text
    state = parse_qs(urlsplit(started.json()["url"]).query)["state"][0]
    return await client.post(
        "/api/v1/x-connection/authorizations/complete",
        json={"code": "reconnect-code", "state": state},
    )


async def test_reconnect_refreshes_the_x_photo_without_offering_photo_choices(
    client, x_identity, fake_x_publisher, fake_photo_fetcher
):
    photo_url = "https://pbs.twimg.com/profile_images/ada.jpg"
    fake_x_publisher.account = replace(fake_x_publisher.account, photo_url=photo_url)
    fake_photo_fetcher.photos[photo_url] = "data:image/jpeg;base64,eA=="

    restored = await authorize(client)

    assert restored.status_code == 200
    assert restored.json()["offer_photo"] is False
    assert (await client.get("/api/v1/users/me")).json()[
        "avatar_data_url"
    ] == "data:image/jpeg;base64,eA=="


@pytest.mark.parametrize("action", ["use", "decline"])
async def test_x_identity_cannot_use_legacy_photo_actions(
    client, x_identity, subscribed, fake_x_publisher, fake_photo_fetcher, action
):
    photo_url = "https://pbs.twimg.com/profile_images/ada.jpg"
    fake_x_publisher.account = replace(fake_x_publisher.account, photo_url=photo_url)
    fake_photo_fetcher.photos[photo_url] = "data:image/jpeg;base64,eA=="
    assert (await authorize(client)).status_code == 200
    fake_photo_fetcher.fetched.clear()

    rejected = await client.post(f"/api/v1/x-connection/photo/{action}")

    assert rejected.status_code == 404
    assert fake_photo_fetcher.fetched == []


async def test_existing_publish_refresh_updates_x_photo_without_an_extra_x_call(
    client, x_identity, subscribed, fixed_clock, fake_x_publisher, fake_photo_fetcher, post_with
):
    old_url = "https://pbs.twimg.com/profile_images/ada.jpg"
    new_url = "https://pbs.twimg.com/profile_images/new.jpg"
    fake_x_publisher.account = replace(fake_x_publisher.account, photo_url=old_url)
    fake_photo_fetcher.photos[old_url] = "data:image/jpeg;base64,eA=="
    fake_photo_fetcher.photos[new_url] = "data:image/jpeg;base64,eQ=="
    spy = AsyncMock(wraps=fake_x_publisher.fetch_account)
    fake_x_publisher.fetch_account = spy
    assert (await authorize(client)).status_code == 200
    fixed_clock.advance(timedelta(hours=2))
    fake_x_publisher.account = replace(fake_x_publisher.account, photo_url=new_url)

    published = await client.post(
        "/api/v1/scheduled-posts",
        json={
            "post_id": await post_with("A new photo during ordinary refresh"),
            "publish_now": True,
        },
    )

    assert published.status_code == 201, published.text
    assert (await client.get("/api/v1/users/me")).json()[
        "avatar_data_url"
    ] == "data:image/jpeg;base64,eQ=="
    assert len(fake_x_publisher.refreshes) == 1
    assert spy.await_count == 2


@pytest.mark.parametrize("outcome", ["removed", "unavailable", "download_failed"])
async def test_publish_photo_refresh_distinguishes_removal_from_failure(
    client,
    x_identity,
    subscribed,
    fixed_clock,
    fake_x_publisher,
    fake_photo_fetcher,
    post_with,
    outcome,
):
    old_url = "https://pbs.twimg.com/profile_images/ada.jpg"
    old_photo = "data:image/jpeg;base64,eA=="
    fake_x_publisher.account = replace(fake_x_publisher.account, photo_url=old_url)
    fake_photo_fetcher.photos[old_url] = old_photo
    assert (await authorize(client)).status_code == 200
    fixed_clock.advance(timedelta(hours=2))
    fake_x_publisher.account = replace(
        fake_x_publisher.account,
        photo_url="https://pbs.twimg.com/profile_images/unavailable.jpg"
        if outcome == "download_failed"
        else None,
    )
    if outcome == "unavailable":
        fake_x_publisher.fail_fetch_account = XPublisherError("unavailable")

    published = await client.post(
        "/api/v1/scheduled-posts",
        json={"post_id": await post_with("Photo refresh result"), "publish_now": True},
    )

    assert published.status_code == 201, published.text
    expected = None if outcome == "removed" else old_photo
    assert (await client.get("/api/v1/users/me")).json()["avatar_data_url"] == expected


async def test_x_identity_can_restore_publishing_without_a_subscription(
    client, db, x_identity, connect_x, clock
):
    await connect_x()
    connection = await db.scalar(select(XConnection).where(XConnection.user_id == x_identity.id))
    assert connection is not None
    connection.needs_reconnect = True
    await db.commit()

    restored = await authorize(client)

    assert restored.status_code == 200, restored.text
    assert restored.json()["handle"] == "ada"
    assert restored.json()["needs_reconnect"] is False
    assert (await client.get("/api/v1/x-connection")).status_code == 200
    assert (await client.get("/api/v1/users/me")).status_code == 200


async def test_reconnecting_another_x_id_preserves_credentials_and_waiting_posts(
    client, x_identity, subscribed, connect_x, fixed_clock, fake_x_publisher, post_with
):
    await connect_x()
    waiting_post = await post_with("Keep waiting for the original account")
    scheduled = await client.post(
        "/api/v1/scheduled-posts",
        json={"post_id": waiting_post, "publish_at": "2026-10-11T09:00:00Z"},
    )
    assert scheduled.status_code == 201, scheduled.text
    original_account = fake_x_publisher.account
    fake_x_publisher.account = replace(original_account, user_id="2002", handle="other")

    refused = await authorize(client)

    assert refused.status_code == 409, refused.text
    assert "@ada" in refused.json()["detail"]
    assert "same X account" in refused.json()["detail"]
    connection = (await client.get("/api/v1/x-connection")).json()
    assert connection["handle"] == "ada"
    assert connection["scheduled_posts_waiting"] == 1
    assert (await client.get(f"/api/v1/posts/{waiting_post}")).json()["status"] == "scheduled"
    posted = await client.post(
        "/api/v1/scheduled-posts",
        json={"post_id": await post_with("Still the original credentials"), "publish_now": True},
    )
    assert posted.status_code == 201, posted.text
    assert fake_x_publisher.published[0][0] == "access-1001-1"
    fake_x_publisher.account = original_account
    assert (await authorize(client)).status_code == 200


async def test_x_identity_cannot_disconnect_or_revoke_its_publishing_grant(
    client, x_identity, connect_x, subscribed, clock, fake_x_publisher
):
    await connect_x()

    refused = await client.delete("/api/v1/x-connection")

    assert refused.status_code == 405, refused.text
    assert (await client.get("/api/v1/x-connection")).json()["handle"] == "ada"
    assert fake_x_publisher.revoked == []


async def test_reconnect_requires_every_publishing_scope_without_replacing_credentials(
    client, x_identity, subscribed, connect_x, clock, fake_x_publisher
):
    await connect_x()
    fake_x_publisher.exchange_scope = "tweet.read users.read offline.access"

    refused = await authorize(client)

    assert refused.status_code == 400, refused.text
    unchanged = (await client.get("/api/v1/x-connection")).json()
    assert unchanged["needs_reconnect"] is False
    assert unchanged["needs_reconnect_for_media"] is False


async def test_known_missing_publishing_permission_blocks_posting_until_reconnect(
    client, db, x_identity, subscribed, connect_x, clock, fake_x_publisher, post_with
):
    await connect_x()
    connection = await db.scalar(select(XConnection).where(XConnection.user_id == x_identity.id))
    assert connection is not None
    connection.scopes = "tweet.read users.read offline.access media.write"
    await db.commit()

    found = await client.get("/api/v1/x-connection")

    assert found.json()["needs_reconnect"] is True
    blocked = await client.post(
        "/api/v1/scheduled-posts",
        json={
            "post_id": await post_with("Wait for all publishing permissions"),
            "publish_now": True,
        },
    )
    assert blocked.status_code == 409
    assert fake_x_publisher.published == []
    assert (await authorize(client)).json()["needs_reconnect"] is False


async def test_refresh_losing_publishing_permission_sends_no_post(
    client, x_identity, subscribed, connect_x, fixed_clock, fake_x_publisher, post_with
):
    await connect_x()
    fixed_clock.advance(timedelta(hours=2))
    fake_x_publisher.refresh_scope = "tweet.read users.read offline.access media.write"

    attempted = await client.post(
        "/api/v1/scheduled-posts",
        json={
            "post_id": await post_with("Restore permission before publishing"),
            "publish_now": True,
        },
    )

    assert attempted.status_code == 201, attempted.text
    assert fake_x_publisher.published == []
    assert (await client.get("/api/v1/x-connection")).json()["needs_reconnect"] is True


async def test_lost_publishing_and_failed_reconnect_keep_session_writing_and_billing(
    authed_client, db, user, subscribed, connect_x, fixed_clock, fake_x_publisher, post_with
):
    user.x_user_id = "1001"
    user.x_handle = "ada"
    await db.commit()
    await connect_x()
    fake_x_publisher.fail_publish = XReconnectNeededError("permission revoked")
    attempted = await authed_client.post(
        "/api/v1/scheduled-posts",
        json={"post_id": await post_with("Cannot publish until reconnected"), "publish_now": True},
    )
    assert attempted.status_code == 201, attempted.text
    assert (await authed_client.get("/api/v1/x-connection")).json()["needs_reconnect"] is True

    fake_x_publisher.fail_exchange = XPublisherError("provider unavailable")
    refused = await authorize(authed_client)

    assert refused.status_code == 502
    assert (await authed_client.get("/api/v1/users/me")).status_code == 200
    assert (await authed_client.get("/api/v1/billing/me")).status_code == 200
    edited = await authed_client.put(
        f"/api/v1/posts/{await post_with('Still writing')}/text",
        json={"parts": ["Edited while offline"]},
    )
    assert edited.status_code == 200, edited.text
    assert (await authed_client.post("/api/v1/refresh-token")).status_code == 200


async def test_supported_deletion_does_not_require_restoring_x_authorization(
    authed_client, db, db_session_maker, user, connect_x, clock, fake_billing, file_storage
):
    user.x_user_id = "1001"
    user.x_handle = "ada"
    await db.commit()
    await connect_x()
    connection = await db.scalar(select(XConnection).where(XConnection.user_id == user.id))
    assert connection is not None
    connection.needs_reconnect = True
    await db.commit()
    errors = StringIO()

    result = await run_cli(
        ["--user-id", user.id],
        sessions=db_session_maker,
        gateway=fake_billing,
        storage=file_storage,
        stdout=StringIO(),
        stderr=errors,
    )

    assert result == 0, errors.getvalue()
    assert (await authed_client.get("/api/v1/users/me")).status_code == 401
