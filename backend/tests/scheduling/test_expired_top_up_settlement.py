from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from pumpkit.billing.gateway import SubscriptionState
from pumpkit.core.config import settings
from pumpkit.scheduling.publisher import run_pass
from pumpkit.x_connection.x_publisher import XRateLimitedError
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_top_ups import _send
from tests.billing.test_top_ups import sells_top_ups as sells_top_ups
from tests.scheduling.test_x_posts_top_ups import (
    CUSTOMER,
    _buy_top_up,
    _schedule,
    _utc,
    _x_posts_left,
)
from tests.scheduling.test_x_posts_top_ups import ready as ready


async def restore_paid_access(client, fake_billing, fixed_clock, old):
    fake_billing.set_subscription(CUSTOMER, replace(old, status="canceled"))
    fake_billing.set_subscription(
        CUSTOMER,
        SubscriptionState(
            id="sub_resumed",
            status="active",
            price_id="price_monthly",
            plan_key="pumpkit_pro_monthly",
            created_at=fixed_clock(),
            billing_cycle_anchor=fixed_clock(),
            current_period_end=fixed_clock() + timedelta(days=30),
        ),
    )
    assert (
        await _send(
            client,
            fake_billing,
            "evt_resumed",
            "customer.subscription.created",
            {"customer": CUSTOMER},
        )
    ).status_code == 200


@pytest.mark.parametrize("accepted", [0, 5])
@pytest.mark.parametrize("status", ["active", "trialing", "canceled"])
async def test_delayed_first_attempt_refunds_unaccepted_units_without_releasing_future_reservations(
    client,
    ready,
    subscribed,
    post_with,
    fake_billing,
    fixed_clock,
    fake_x_publisher,
    file_storage,
    db_session_maker,
    status,
    accepted,
):
    await _buy_top_up(client, fake_billing, "cs_first", _utc(2026, 10, 3))
    await _buy_top_up(client, fake_billing, "cs_second", _utc(2026, 10, 4))
    first = await _schedule(client, post_with, "2026-10-10T12:02:00Z", *["Part"] * 6)
    later = await _schedule(client, post_with, "2026-10-15T09:00:00Z", *["Later"] * 6)
    assert first.status_code == later.status_code == 201
    assert await _x_posts_left(client) == (0, [0, 0])
    if accepted:
        fake_x_publisher.fail_publish = XRateLimitedError()
        fake_x_publisher.fail_publish_on = accepted + 1
        fixed_clock.advance(timedelta(minutes=2))
        await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
        fake_x_publisher.fail_publish = None
        fake_x_publisher.fail_publish_on = None
    old = SubscriptionState(
        id=subscribed.stripe_subscription_id,
        status=status,
        price_id="price_monthly",
        plan_key="pumpkit_pro_monthly",
        created_at=_utc(2026, 10, 1),
        billing_cycle_anchor=_utc(2026, 9, 14, 9),
        current_period_end=_utc(2026, 10, 14, 9),
        cancel_at=_utc(2026, 10, 10, 12, 3),
    )
    fake_billing.set_subscription(CUSTOMER, old)
    await _send(
        client,
        fake_billing,
        "evt_cancellation",
        "customer.subscription.updated",
        {"customer": CUSTOMER},
    )
    fixed_clock.advance(timedelta(minutes=3))
    assert (await client.get("/api/v1/billing/me")).json()["subscribed"] is False
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    assert len(fake_x_publisher.published) == accepted + bool(accepted)
    assert (await client.get("/api/v1/usage")).status_code == 403
    await restore_paid_access(client, fake_billing, fixed_clock, old)
    assert (await client.get("/api/v1/posts/" + first.json()["post_id"])).json()["scheduled_post"][
        "state"
    ] == "failed"
    assert (await _x_posts_left(client))[1] == [1 if accepted else 2, 0]
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    assert (await _x_posts_left(client))[1] == [1 if accepted else 2, 0]
    assert (await client.delete("/api/v1/scheduled-posts/" + first.json()["id"])).status_code == 204
    assert (await _x_posts_left(client))[1] == [1 if accepted else 2, 0]


@pytest.mark.parametrize("provider_copy", [False, True])
@pytest.mark.parametrize("accepted,delete_waiting", [(0, False), (5, False), (5, True)])
async def test_purged_free_history_refunds_only_unaccepted_units_and_survives_replay_and_delete(
    authed_client,
    coupons,
    db,
    user,
    post_with,
    connect_x,
    fake_billing,
    fixed_clock,
    fake_x_publisher,
    file_storage,
    db_session_maker,
    monkeypatch,
    sells_top_ups,
    accepted,
    provider_copy,
    delete_waiting,
):
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 4)
    monkeypatch.setattr(settings, "X_LINK_POSTS_MONTHLY_CAP", 2)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).status_code == 200
    user.stripe_customer_id = CUSTOMER
    await db.commit()
    await connect_x()
    await _buy_top_up(authed_client, fake_billing, "cs_first", _utc(2026, 10, 3))
    provider = None
    if provider_copy:
        provider = SubscriptionState(
            id="sub_deferral",
            status="trialing",
            price_id="price_monthly",
            plan_key="pumpkit_pro_monthly",
            created_at=_utc(2026, 10, 1),
            cancel_at=datetime.fromisoformat(offer["ends_at"].replace("Z", "+00:00")),
            trial_start=fixed_clock(),
            trial_end=datetime.fromisoformat(offer["ends_at"].replace("Z", "+00:00")),
            billing_cycle_anchor=datetime.fromisoformat(offer["ends_at"].replace("Z", "+00:00")),
            current_period_end=datetime.fromisoformat(offer["ends_at"].replace("Z", "+00:00")),
        )
        fake_billing.set_subscription(CUSTOMER, provider)
        await _send(
            authed_client,
            fake_billing,
            "evt_provider_deferral",
            "customer.subscription.updated",
            {"customer": CUSTOMER},
        )
    post_id = await post_with(*["Part"] * 6)
    scheduled = await authed_client.post(
        "/api/v1/scheduled-posts", json={"post_id": post_id, "publish_at": "2026-10-10T12:02:00Z"}
    )
    assert scheduled.status_code == 201
    if accepted:
        fake_x_publisher.fail_publish = XRateLimitedError()
        fake_x_publisher.fail_publish_on = accepted + 1
        fixed_clock.advance(timedelta(minutes=2))
        await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
        assert len(fake_x_publisher.published) == accepted + bool(accepted)
        fake_x_publisher.fail_publish = None
        fake_x_publisher.fail_publish_on = None
    target = datetime.fromisoformat(offer["ends_at"].replace("Z", "+00:00"))
    fixed_clock.advance(target + timedelta(days=91) - fixed_clock())
    await coupons(command="purge")
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).status_code == 404
    if not delete_waiting:
        await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    assert len(fake_x_publisher.published) == accepted + bool(accepted)
    if provider is not None:
        fake_billing.set_subscription(CUSTOMER, replace(provider, status="canceled"))
        await _send(
            authed_client,
            fake_billing,
            "evt_ended_deferral",
            "customer.subscription.deleted",
            {"customer": CUSTOMER},
        )
    another = await coupons("--months", "1")
    preview = (await authed_client.post(PREVIEW, json={"code": another["code"]})).json()
    assert (
        await authed_client.post(REDEEM, json=confirmation(preview, "new-access-after-failure"))
    ).status_code == 200
    if delete_waiting:
        assert (
            await authed_client.delete("/api/v1/scheduled-posts/" + scheduled.json()["id"])
        ).status_code == 204
    else:
        assert (await authed_client.get("/api/v1/posts/" + post_id)).json()["scheduled_post"][
            "state"
        ] == "failed"
    assert (await _x_posts_left(authed_client))[1] == [1 if accepted else 2]
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    assert (await _x_posts_left(authed_client))[1] == [1 if accepted else 2]
    assert (
        await authed_client.delete("/api/v1/scheduled-posts/" + scheduled.json()["id"])
    ).status_code == (404 if delete_waiting else 204)
    assert (await _x_posts_left(authed_client))[1] == [1 if accepted else 2]
