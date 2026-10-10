from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from fastapi import Depends
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.security import decrypt
from app.core.x_publisher import (
    XAccount,
    XPublisherError,
    XReconnectNeededError,
    code_challenge_for,
)
from app.db.models import Subscription, User, XConnection
from app.db.session import get_async_db
from app.main import app

X_CONNECTION = "/api/v1/x-connection"
AUTHORIZATIONS = f"{X_CONNECTION}/authorizations"
COMPLETE = f"{AUTHORIZATIONS}/complete"


async def _start(client: AsyncClient) -> dict[str, str]:
    """Start an authorization; returns the authorize URL's query (state, code_challenge)."""
    started = await client.post(AUTHORIZATIONS)
    assert started.status_code == 200, started.text
    query = parse_qs(urlsplit(started.json()["url"]).query)
    return {key: values[0] for key, values in query.items()}


async def _connect(client: AsyncClient, code: str = "the-code"):
    """Run the whole consent: start, then complete with the state X sends back."""
    state = (await _start(client))["state"]
    return await client.post(COMPLETE, json={"code": code, "state": state})


async def test_a_user_without_an_x_connection_gets_404(client):
    response = await client.get(X_CONNECTION)

    assert response.status_code == 404


async def test_a_subscribed_user_connects_and_then_sees_their_handle(
    client, subscribed, fake_x_publisher, clock
):
    query = await _start(client)

    completed = await client.post(COMPLETE, json={"code": "the-code", "state": query["state"]})

    assert completed.status_code == 200
    expected = {
        "handle": "ada",
        "char_limit": 280,
        "needs_reconnect": False,
        "scheduled_posts_waiting": 0,
    }
    assert completed.json() == expected
    assert (await client.get(X_CONNECTION)).json() == expected
    [(code, verifier)] = fake_x_publisher.exchanges
    assert code == "the-code"
    assert code_challenge_for(verifier) == query["code_challenge"]


async def test_the_x_connection_outlives_the_session_it_was_made_in(
    new_browser, sign_in_by_magic_link, user, subscribed, clock
):
    first = new_browser()
    signed_in = await sign_in_by_magic_link(first, user.email)
    first.headers["Authorization"] = f"Bearer {signed_in.access_token}"
    assert (await _connect(first)).status_code == 200
    assert (await first.post("/api/v1/logout")).status_code == 200

    second = new_browser()
    signed_in = await sign_in_by_magic_link(second, user.email)
    second.headers["Authorization"] = f"Bearer {signed_in.access_token}"
    response = await second.get(X_CONNECTION)

    assert response.status_code == 200
    assert response.json()["handle"] == "ada"


async def test_connecting_another_x_account_replaces_the_x_connection(
    client, subscribed, fake_x_publisher, clock
):
    await _connect(client)
    fake_x_publisher.account = XAccount(user_id="2002", handle="grace", subscription_type="None")

    response = await _connect(client)

    assert response.status_code == 200
    assert (await client.get(X_CONNECTION)).json()["handle"] == "grace"


async def test_an_x_account_connected_to_another_user_is_refused(
    client, db, subscribed, fake_x_publisher, clock
):
    await _connect(client)
    switch_back = await _sign_in_as_another_subscribed_user(db)

    response = await _connect(client)

    assert response.status_code == 409
    assert response.json()["detail"] == "@ada is already connected to another Pumpkit account."
    assert (await client.get(X_CONNECTION)).status_code == 404
    switch_back()
    assert (await client.get(X_CONNECTION)).json()["handle"] == "ada"


async def test_an_unknown_state_is_refused_without_calling_x(
    client, subscribed, fake_x_publisher, clock
):
    await _start(client)

    response = await client.post(COMPLETE, json={"code": "c", "state": "made-up"})

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "This X authorization expired or was already used. Connect X again."
    )
    assert fake_x_publisher.exchanges == []


async def test_a_state_is_refused_ten_minutes_after_it_was_issued(
    client, subscribed, fake_x_publisher, clock
):
    state = (await _start(client))["state"]
    clock.advance(timedelta(minutes=10))

    response = await client.post(COMPLETE, json={"code": "c", "state": state})

    assert response.status_code == 400
    assert fake_x_publisher.exchanges == []


async def test_a_state_works_just_before_it_expires(client, subscribed, clock):
    state = (await _start(client))["state"]
    clock.advance(timedelta(minutes=9, seconds=59))

    response = await client.post(COMPLETE, json={"code": "c", "state": state})

    assert response.status_code == 200


async def test_a_state_is_used_once(client, subscribed, fake_x_publisher, clock):
    state = (await _start(client))["state"]
    await client.post(COMPLETE, json={"code": "c", "state": state})

    response = await client.post(COMPLETE, json={"code": "c", "state": state})

    assert response.status_code == 400
    assert len(fake_x_publisher.exchanges) == 1


async def test_a_state_is_spent_even_when_x_fails(client, subscribed, fake_x_publisher, clock):
    state = (await _start(client))["state"]
    fake_x_publisher.fail_exchange = XPublisherError("X is down")
    assert (await client.post(COMPLETE, json={"code": "c", "state": state})).status_code == 502
    fake_x_publisher.fail_exchange = None

    response = await client.post(COMPLETE, json={"code": "c", "state": state})

    assert response.status_code == 400


async def test_another_users_state_is_refused(client, db, subscribed, fake_x_publisher, clock):
    state = (await _start(client))["state"]
    await _sign_in_as_another_subscribed_user(db)

    response = await client.post(COMPLETE, json={"code": "c", "state": state})

    assert response.status_code == 400
    assert fake_x_publisher.exchanges == []


async def test_a_grant_x_refuses_asks_the_user_to_connect_again(
    client, subscribed, fake_x_publisher, clock
):
    fake_x_publisher.fail_exchange = XReconnectNeededError("no refresh token")

    response = await _connect(client)

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "X didn't give Pumpkit access to your account. Connect X again."
    )
    assert (await client.get(X_CONNECTION)).status_code == 404


async def test_x_failing_during_the_exchange_is_reported_as_a_502(
    client, subscribed, fake_x_publisher, assert_reported_502, clock
):
    fake_x_publisher.fail_exchange = XPublisherError("X is down")

    response = await _connect(client)

    assert_reported_502(response)


async def test_without_the_x_app_settings_connecting_says_so(
    client, subscribed, fake_x_publisher, clock
):
    fake_x_publisher.not_configured = True

    response = await client.post(AUTHORIZATIONS)

    assert response.status_code == 503
    assert "X_CLIENT_ID" in response.json()["detail"]


async def test_disconnecting_removes_the_x_connection_and_revokes_its_grant(
    client, subscribed, fake_x_publisher, clock
):
    await _connect(client)

    response = await client.delete(X_CONNECTION)

    assert response.status_code == 204
    assert (await client.get(X_CONNECTION)).status_code == 404
    assert fake_x_publisher.revoked == ["refresh-1001-1"]


async def test_the_x_connection_counts_the_scheduled_posts_waiting_to_go_out_on_it(
    client, subscribed, fake_x_publisher, fixed_clock
):
    await _connect(client)
    for text in ("One", "Two"):
        await client.post(
            "/api/v1/scheduled-posts", json={"text": text, "publish_at": "2026-10-11T09:00:00Z"}
        )
    await client.post("/api/v1/scheduled-posts", json={"text": "Gone", "publish_now": True})

    response = await client.get(X_CONNECTION)

    assert response.json()["scheduled_posts_waiting"] == 2


async def test_scheduled_posts_waiting_for_another_x_account_are_not_counted(
    client, subscribed, fake_x_publisher, fixed_clock
):
    await _connect(client)
    await client.post(
        "/api/v1/scheduled-posts", json={"text": "For ada", "publish_at": "2026-10-11T09:00:00Z"}
    )
    fake_x_publisher.account = XAccount(user_id="2002", handle="grace", subscription_type="None")

    connected = await _connect(client)

    assert connected.json()["scheduled_posts_waiting"] == 0


async def test_disconnecting_succeeds_when_x_fails_to_revoke(
    client, subscribed, fake_x_publisher, clock
):
    await _connect(client)
    fake_x_publisher.fail_revoke = True

    response = await client.delete(X_CONNECTION)

    assert response.status_code == 204
    assert (await client.get(X_CONNECTION)).status_code == 404


async def test_disconnecting_without_an_x_connection_returns_404(client):
    response = await client.delete(X_CONNECTION)

    assert response.status_code == 404


async def test_a_user_who_is_not_subscribed_cannot_connect(client, fake_x_publisher, clock):
    started = await client.post(AUTHORIZATIONS)
    completed = await client.post(COMPLETE, json={"code": "c", "state": "s"})

    assert started.status_code == 403
    assert completed.status_code == 403
    assert fake_x_publisher.exchanges == []


async def test_a_user_whose_subscription_ended_can_still_see_and_disconnect_x(
    client, db, subscribed, clock
):
    await _connect(client)
    subscribed.status = "canceled"
    await db.commit()

    assert (await client.get(X_CONNECTION)).status_code == 200
    assert (await client.delete(X_CONNECTION)).status_code == 204


async def test_tokens_are_stored_encrypted_and_never_returned(client, db, user, subscribed, clock):
    completed = await _connect(client)

    assert "access-1001-1" not in completed.text and "refresh-1001-1" not in completed.text
    stored = (
        await db.execute(select(XConnection).where(XConnection.user_id == user.id))
    ).scalar_one()
    assert stored.access_token_encrypted != "access-1001-1"
    assert decrypt(stored.access_token_encrypted) == "access-1001-1"
    assert stored.refresh_token_encrypted != "refresh-1001-1"
    assert decrypt(stored.refresh_token_encrypted) == "refresh-1001-1"


async def _sign_in_as_another_subscribed_user(db) -> Callable[[], None]:
    """Make `client` act as Bob, a second Subscribed User; call the result to switch back."""
    other = User(email="bob@example.com", display_name="Bob")
    db.add(other)
    await db.flush()
    db.add(
        Subscription(
            user_id=other.id,
            stripe_subscription_id="sub_bob",
            stripe_customer_id="cus_bob",
            status="active",
            stripe_created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    )
    await db.commit()
    other_id = other.id

    async def _other(request_db: AsyncSession = Depends(get_async_db)) -> User:
        loaded = await request_db.get(User, other_id)
        assert loaded is not None
        return loaded

    previous = app.dependency_overrides[get_current_user]
    app.dependency_overrides[get_current_user] = _other

    def _switch_back() -> None:
        app.dependency_overrides[get_current_user] = previous

    return _switch_back
