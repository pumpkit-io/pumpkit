from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select

from pumpkit.billing.models import Subscription
from pumpkit.scheduling.publisher import run_pass
from tests.billing.test_annual_trial_coupons import at
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_monthly_coupons import monthly
from tests.billing.test_top_ups import _send


@pytest.mark.parametrize("interval", ["month", "year"])
@pytest.mark.parametrize("webhook_first", [False, True])
async def test_cancelled_paid_claim_keeps_cancellation_paid_resets_and_every_free_month(
    authed_client, coupons, db, user, fake_billing, fixed_clock, interval, webhook_first
):
    fixed_clock.advance(at("2028-02-10T12:00:00") - fixed_clock())
    state = await monthly(db, user, fake_billing, fixed_clock)
    paid_end = at("2028-02-29T12:00:00") if interval == "month" else at("2029-01-31T12:00:00")
    state = replace(
        state,
        interval=interval,
        current_period_start=at("2028-01-31T12:00:00"),
        billing_cycle_anchor=at("2028-01-31T12:00:00"),
        current_period_end=paid_end,
        cancel_at=paid_end,
    )
    fake_billing.set_subscription("cus_monthly", state)
    if webhook_first:
        await _send(
            authed_client,
            fake_billing,
            "evt_cancel_before",
            "customer.subscription.updated",
            {"customer": "cus_monthly"},
        )
    created = await coupons("--months", "1")
    preview = await authed_client.post(PREVIEW, json={"code": created["code"]})
    assert preview.status_code == 200, preview.text
    offer = preview.json()
    assert offer["starts_at"] == paid_end.isoformat().replace("+00:00", "Z")
    assert offer["next_payment_at"] is None
    request = confirmation(offer)
    result = await authed_client.post(REDEEM, json=request)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed"
    assert result.json()["next_payment_at"] is None
    assert fake_billing.deferrals == []
    assert (await fake_billing.list_subscriptions(customer_id="cus_monthly"))[0] == state
    fake_billing.set_subscription("cus_monthly", replace(state, status="canceled"))
    for event_id in ("evt_ended", "evt_ended", "evt_older_active"):
        await _send(
            authed_client,
            fake_billing,
            event_id,
            "customer.subscription.updated",
            {"customer": "cus_monthly", "status": "active"},
        )
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["status"] == "canceled"
    assert me["subscription"]["paid_through"] == offer["starts_at"]
    assert me["subscribed"] is True
    assert (await authed_client.get("/api/v1/usage")).json()["allowance"][
        "resets_at"
    ] == "2028-02-29T12:00:00Z"
    assert (await authed_client.post(REDEEM, json=request)).json() == result.json()
    second = await coupons("--months", "1")
    second_preview = await authed_client.post(PREVIEW, json={"code": second["code"]})
    assert second_preview.status_code == 200, second_preview.text
    second_offer = second_preview.json()
    assert second_offer["starts_at"] == offer["ends_at"]
    assert second_offer["next_payment_at"] is None
    assert (
        await authed_client.post(REDEEM, json=confirmation(second_offer, "cancelled-second-0001"))
    ).json()["status"] == "completed"
    assert fake_billing.deferrals == []
    assert (await authed_client.post("/api/v1/billing/subscribe-now")).status_code == 409
    assert (await authed_client.post("/api/v1/billing/portal")).status_code == 200
    assert fake_billing.restricted_portals == ["cus_monthly"]
    fixed_clock.advance(paid_end - fixed_clock())
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscribed"] is True
    assert me["free_access"]["current_ends_at"] == offer["ends_at"]
    assert (await authed_client.get("/api/v1/usage")).json()["allowance"]["generations"][
        "limit"
    ] == 500
    end = at(second_offer["ends_at"].removesuffix("Z"))
    fixed_clock.advance(end - timedelta(seconds=1) - fixed_clock())
    assert (await authed_client.get("/api/v1/billing/me")).json()["subscribed"] is True
    fixed_clock.advance(timedelta(seconds=1))
    assert (await authed_client.get("/api/v1/billing/me")).json()["subscribed"] is False
    assert (await authed_client.get("/api/v1/onboarding")).json()["next_step"] == "paywall"
    assert (await authed_client.get("/api/v1/usage")).status_code == 403


async def test_ended_paid_access_schedules_into_all_free_months_and_publisher_stops_at_end(
    authed_client,
    coupons,
    db,
    user,
    fake_billing,
    fixed_clock,
    connect_x,
    post_with,
    db_session_maker,
    fake_x_publisher,
    file_storage,
):
    fixed_clock.advance(timedelta(seconds=-fixed_clock().second))
    state = await monthly(db, user, fake_billing, fixed_clock)
    fake_billing.set_subscription("cus_monthly", replace(state, cancel_at=state.current_period_end))
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "completed"
    fake_billing.set_subscription("cus_monthly", replace(state, status="canceled"))
    await _send(
        authed_client,
        fake_billing,
        "evt_ended_no_cancel_date",
        "customer.subscription.deleted",
        {"customer": "cus_monthly"},
    )
    await connect_x()
    post_id = await post_with("Earned free coverage")
    end = at(offer["ends_at"].removesuffix("Z"))
    refused = await authed_client.post(
        "/api/v1/scheduled-posts", json={"post_id": post_id, "publish_at": end.isoformat()}
    )
    assert refused.status_code == 409 and refused.json()["code"] == "SUBSCRIPTION_ENDS"
    queued = await authed_client.post(
        "/api/v1/scheduled-posts",
        json={"post_id": post_id, "publish_at": (end - timedelta(minutes=1)).isoformat()},
    )
    assert queued.status_code == 201, queued.text
    fixed_clock.advance(end - fixed_clock())
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    assert fake_x_publisher.published == []


@pytest.mark.parametrize("after_mutation", [False, True])
async def test_cancellation_during_confirmation_completes_once_without_reactivating(
    authed_client, coupons, db, user, fake_billing, fixed_clock, after_mutation
):
    state = await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    fake_billing.fail_on.add("after_defer_renewal" if after_mutation else "defer_renewal")
    request = confirmation(offer)
    assert (await authed_client.post(REDEEM, json=request)).json()["status"] == "pending"
    current = (await fake_billing.list_subscriptions(customer_id="cus_monthly"))[0]
    fake_billing.set_subscription(
        "cus_monthly", replace(current, status="canceled", cancel_at=fixed_clock())
    )
    fake_billing.fail_on.clear()
    for event_id in ("evt_cancel_pending", "evt_cancel_pending", "evt_old_pending"):
        await _send(
            authed_client,
            fake_billing,
            event_id,
            "customer.subscription.deleted",
            {"customer": "cus_monthly"},
        )
    recovered = await authed_client.get(REDEEM + "/redeem-test-0001")
    assert recovered.json()["status"] == "completed", recovered.text
    assert recovered.json()["next_payment_at"] is None
    assert len(fake_billing.deferrals) == (1 if after_mutation else 0)
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 1
    assert (await authed_client.post(REDEEM, json=request)).json() == recovered.json()
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscribed"] and me["subscription"]["paid_through"] == offer["starts_at"]
    assert me["free_access"]["ends_at"] == offer["ends_at"]
    assert state.current_period_end is not None
    fixed_clock.advance(state.current_period_end - fixed_clock())
    assert (await authed_client.get("/api/v1/usage")).json()["allowance"]["generations"][
        "limit"
    ] == 500


@pytest.mark.parametrize(
    "problem", ["debt", "checkout", "pending", "schedule", "unsettled", "horizon"]
)
async def test_cancelled_claim_keeps_payment_change_and_horizon_guards_without_consuming(
    authed_client, coupons, db, user, fake_billing, fixed_clock, problem
):
    state = await monthly(db, user, fake_billing, fixed_clock)
    state = replace(state, cancel_at=state.current_period_end)
    if problem == "pending":
        state = replace(state, has_pending_update=True)
    if problem == "schedule":
        state = replace(state, schedule_id="sched_change")
    if problem == "unsettled":
        state = replace(state, paid_current_period=False)
    fake_billing.set_subscription("cus_monthly", state)
    if problem == "debt":
        fake_billing.unsettled_invoice_customers.add("cus_monthly")
    if problem == "checkout":
        await fake_billing.create_subscription_checkout(
            customer_id="cus_monthly",
            price_id="price_monthly",
            quantity=1,
            user_id=user.id,
            trial_period_days=None,
        )
    created = await coupons("--months", "24" if problem == "horizon" else "1")
    response = await authed_client.post(PREVIEW, json={"code": created["code"]})
    assert response.status_code == 409, response.text
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0
    assert fake_billing.deferrals == []


async def test_cancellation_between_preview_and_confirmation_requires_new_no_payment_offer(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    state = await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    fake_billing.set_subscription("cus_monthly", replace(state, cancel_at=state.current_period_end))
    stale = await authed_client.post(REDEEM, json=confirmation(offer))
    assert stale.status_code == 409
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0
    updated = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    assert updated["next_payment_at"] is None
    assert (await authed_client.post(REDEEM, json=confirmation(updated))).json()[
        "status"
    ] == "completed"
    assert fake_billing.deferrals == []


async def test_cancelled_snapshot_is_minimized_only_after_all_related_grants_end(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    state = await monthly(db, user, fake_billing, fixed_clock)
    fake_billing.set_subscription("cus_monthly", replace(state, cancel_at=state.current_period_end))
    created = await coupons("--months", "1")
    first = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(first))).json()[
        "status"
    ] == "completed"
    fake_billing.set_subscription("cus_monthly", replace(state, status="canceled"))
    assert state.current_period_end is not None
    fixed_clock.advance(state.current_period_end - fixed_clock())
    second = await coupons("--months", "6")
    offer = (await authed_client.post(PREVIEW, json={"code": second["code"]})).json()
    assert (
        await authed_client.post(REDEEM, json=confirmation(offer, "later-cancelled-0001"))
    ).json()["status"] == "completed"
    fixed_clock.advance(timedelta(days=130))
    await coupons(command="purge")
    saved = await db.scalar(
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    assert saved is not None and saved.paid_anchor is not None
    assert (await authed_client.get("/api/v1/usage")).json()["allowance"]["generations"][
        "limit"
    ] == 500
    end = at(offer["ends_at"].removesuffix("Z"))
    fixed_clock.advance(end + timedelta(days=90) - fixed_clock())
    await db.rollback()
    await coupons(command="purge")
    await db.refresh(saved)
    assert (
        saved.paid_start,
        saved.paid_end,
        saved.paid_anchor,
        saved.paid_allowance,
        saved.preserved_trial,
    ) == (None, None, None, None, None)
    assert (await authed_client.get("/api/v1/billing/me")).json()["subscribed"] is False


async def test_current_cancelled_grant_uses_its_subscription_after_older_coverage_ends_and_purge(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    fixed_clock.advance(at("2028-01-15T12:00:00") - fixed_clock())
    first_state = replace(
        await monthly(db, user, fake_billing, fixed_clock),
        billing_cycle_anchor=at("2028-01-01T12:00:00"),
        current_period_start=at("2028-01-01T12:00:00"),
        current_period_end=at("2028-02-01T12:00:00"),
        cancel_at=at("2028-02-01T12:00:00"),
    )
    fake_billing.set_subscription("cus_monthly", first_state)
    first = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": first["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "completed"
    fake_billing.set_subscription("cus_monthly", replace(first_state, status="canceled"))
    fixed_clock.advance(at("2028-03-02T12:00:00") - fixed_clock())
    second_state = replace(
        first_state,
        id="sub_second",
        created_at=at("2028-03-01T12:00:00"),
        billing_cycle_anchor=at("2028-03-01T12:00:00"),
        current_period_start=at("2028-03-01T12:00:00"),
        current_period_end=at("2028-04-01T12:00:00"),
        cancel_at=at("2028-04-01T12:00:00"),
    )
    fake_billing.set_subscription("cus_monthly", second_state)
    second = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": second["code"]})).json()
    assert (
        await authed_client.post(REDEEM, json=confirmation(offer, "second-subscription-0001"))
    ).json()["status"] == "completed"
    fake_billing.set_subscription("cus_monthly", replace(second_state, status="canceled"))
    fixed_clock.advance(at("2028-04-02T12:00:00") - fixed_clock())
    await coupons(command="purge")
    old = await db.scalar(
        select(Subscription).where(Subscription.stripe_subscription_id == first_state.id)
    )
    assert old is not None and old.paid_anchor is not None
    third = await coupons("--months", "6")
    preview = await authed_client.post(PREVIEW, json={"code": third["code"]})
    assert preview.status_code == 200, preview.text
    offer = preview.json()
    assert (offer["starts_at"], offer["ends_at"], offer["next_payment_at"]) == (
        "2028-05-01T12:00:00Z",
        "2028-11-01T12:00:00Z",
        None,
    )
    assert (
        await authed_client.post(REDEEM, json=confirmation(offer, "current-subscription-0001"))
    ).json()["status"] == "completed"
    fixed_clock.advance(at("2028-08-02T12:00:00") - fixed_clock())
    await db.rollback()
    await coupons(command="purge")
    assert (await authed_client.get(REDEEM + "/second-subscription-0001")).status_code == 404
    assert (await authed_client.get(REDEEM + "/current-subscription-0001")).json()[
        "status"
    ] == "completed"
    fourth = await coupons("--months", "1")
    preview = await authed_client.post(PREVIEW, json={"code": fourth["code"]})
    assert preview.status_code == 200, preview.text
    offer = preview.json()
    assert (offer["starts_at"], offer["ends_at"], offer["next_payment_at"]) == (
        "2028-11-01T12:00:00Z",
        "2028-12-01T12:00:00Z",
        None,
    )
    assert (
        await authed_client.post(REDEEM, json=confirmation(offer, "retained-chain-0001"))
    ).json()["status"] == "completed"
    assert fake_billing.deferrals == []


async def test_cardless_free_time_does_not_bind_to_unrelated_retained_cancelled_history(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    state = await monthly(db, user, fake_billing, fixed_clock)
    fake_billing.set_subscription("cus_monthly", replace(state, cancel_at=state.current_period_end))
    first = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": first["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "completed"
    end = at(offer["ends_at"].removesuffix("Z"))
    fake_billing.set_subscription("cus_monthly", replace(state, status="canceled", paused=True))
    await _send(
        authed_client,
        fake_billing,
        "evt_old_history_ended",
        "customer.subscription.deleted",
        {"customer": "cus_monthly"},
    )
    fixed_clock.advance(end + timedelta(days=1) - fixed_clock())
    cardless = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": cardless["code"]})).json()
    assert (
        await authed_client.post(REDEEM, json=confirmation(offer, "cardless-history-0001"))
    ).json()["status"] == "completed"
    another = await coupons("--months", "6")
    preview = await authed_client.post(PREVIEW, json={"code": another["code"]})
    assert preview.status_code == 200, preview.text
    offer = preview.json()
    assert offer["next_payment_at"] is None
    assert (
        await authed_client.post(REDEEM, json=confirmation(offer, "cardless-append-0001"))
    ).json()["status"] == "completed"
    fixed_clock.advance(end + timedelta(days=91) - fixed_clock())
    await coupons(command="purge")
    old = await db.scalar(
        select(Subscription)
        .where(Subscription.stripe_subscription_id == state.id)
        .execution_options(populate_existing=True)
    )
    assert old is not None and old.paid_anchor is None
    assert (await authed_client.get("/api/v1/billing/me")).json()["subscribed"] is True
    assert fake_billing.deferrals == []
