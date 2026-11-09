from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.billing.models import Subscription
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_monthly_coupons import monthly
from tests.billing.test_top_ups import ACCEPTANCE, TOP_UP_CHECKOUT, _send
from tests.billing.test_top_ups import sells_top_ups as sells_top_ups
from tests.posts.writing_replies import written


def at(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


async def test_annual_claim_preserves_monthly_resets_then_resumes_full_annual_interval(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    fixed_clock.advance(at("2027-02-15T12:00:00") - fixed_clock())
    state = await monthly(db, user, fake_billing, fixed_clock)
    state = replace(
        state,
        interval="year",
        current_period_start=at("2026-12-01T12:00:00"),
        billing_cycle_anchor=at("2026-12-01T12:00:00"),
        current_period_end=at("2027-12-01T12:00:00"),
    )
    fake_billing.set_subscription("cus_monthly", state)
    created = await coupons("--months", "3")
    preview = await authed_client.post(PREVIEW, json={"code": created["code"]})
    assert preview.status_code == 200, preview.text
    offer = preview.json()
    assert offer["starts_at"] == "2027-12-01T12:00:00Z"
    assert offer["ends_at"] == "2028-03-01T12:00:00Z"
    result = await authed_client.post(REDEEM, json=confirmation(offer))
    assert result.json()["status"] == "completed", result.text
    usage = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert usage["generations"]["limit"] == 500
    assert usage["resets_at"] == "2027-03-01T12:00:00Z"
    fixed_clock.advance(at("2027-11-30T12:00:00") - fixed_clock())
    usage = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert usage["resets_at"] == "2027-12-01T12:00:00Z"
    fixed_clock.advance(timedelta(days=1))
    usage = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert usage["resets_at"] == "2028-01-01T12:00:00Z"
    fake_billing.set_subscription(
        "cus_monthly",
        replace(
            state,
            status="active",
            current_period_start=at("2028-03-01T12:00:00"),
            current_period_end=at("2029-03-01T12:00:00"),
            billing_cycle_anchor=at("2028-03-01T12:00:00"),
        ),
    )
    fixed_clock.advance(at("2028-03-01T12:00:00") - fixed_clock())
    await _send(
        authed_client,
        fake_billing,
        "evt_annual_resumed",
        "customer.subscription.updated",
        {"customer": "cus_monthly"},
    )
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["current_period_end"] == "2029-03-01T12:00:00Z"
    assert me["free_access"] is None
    assert (await authed_client.get("/api/v1/usage")).json()["allowance"][
        "resets_at"
    ] == "2028-04-01T12:00:00Z"


@pytest.mark.parametrize("interval", ["month", "year"])
async def test_existing_trial_keeps_original_reduced_period_then_full_free_months(
    authed_client,
    coupons,
    db,
    user,
    fake_billing,
    fixed_clock,
    interval,
    sells_top_ups,
    fake_x_reader,
    fake_llm,
):
    fixed_clock.advance(at("2028-01-25T12:00:00") - fixed_clock())
    state = await monthly(db, user, fake_billing, fixed_clock)
    state = replace(
        state,
        status="trialing",
        interval=interval,
        paid_current_period=False,
        trial_start=at("2028-01-20T12:00:00"),
        trial_end=at("2028-01-31T12:00:00"),
        current_period_start=at("2028-01-20T12:00:00"),
        current_period_end=at("2028-01-31T12:00:00"),
        billing_cycle_anchor=at("2028-01-31T12:00:00"),
    )
    fake_billing.set_subscription("cus_monthly", state)
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(post_id="trial-author", text="An example", posted_at=fixed_clock())
    ]
    await _send(
        authed_client,
        fake_billing,
        "evt_original_trial",
        "customer.subscription.updated",
        {"customer": "cus_monthly"},
    )
    await authed_client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    fake_llm.replies = [written("Sketch"), {"post": "Usage stays in the original trial"}]
    assert (await authed_client.post("/api/v1/posts", json={"brief": "A note"})).status_code == 201
    created = await coupons("--months", "1")
    preview = await authed_client.post(PREVIEW, json={"code": created["code"]})
    assert preview.status_code == 200, preview.text
    offer = preview.json()
    assert offer["starts_at"] == "2028-01-31T12:00:00Z"
    assert offer["ends_at"] == "2028-02-29T12:00:00Z"
    fake_billing.fail_on.add("after_defer_renewal")
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "pending"
    await _send(
        authed_client,
        fake_billing,
        "evt_trial_uncertain",
        "customer.subscription.updated",
        {"customer": "cus_monthly"},
    )
    usage = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert usage["generations"] == {"limit": 125, "used": 1, "left": 124}
    assert usage["resets_at"] == "2028-01-31T12:00:00Z"
    assert usage["trial"] is True
    assert usage["way_out"] is None
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["paid_through"] is None
    assert me["subscription"]["introductory_trial_end"] == "2028-01-31T12:00:00Z"
    assert (await authed_client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)).status_code == 409
    fake_billing.fail_on.clear()
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "completed"
    second = await coupons("--months", "1")
    next_offer = (await authed_client.post(PREVIEW, json={"code": second["code"]})).json()
    assert next_offer["ends_at"] == "2028-03-31T12:00:00Z"
    assert (
        await authed_client.post(REDEEM, json=confirmation(next_offer, "second-trial-0001"))
    ).json()["status"] == "completed"
    fixed_clock.advance(at("2028-01-31T12:00:00") - fixed_clock())
    usage = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert usage["generations"]["limit"] == 500
    assert usage["resets_at"] == "2028-02-29T12:00:00Z"
    assert usage["trial"] is False
    assert usage["way_out"] == "top_up"
    assert (await authed_client.get("/api/v1/billing/me")).json()["trial_days"] is None
    assert (await authed_client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)).status_code == 200
    resumed_end = "2028-04-30T12:00:00" if interval == "month" else "2029-03-31T12:00:00"
    fake_billing.set_subscription(
        "cus_monthly",
        replace(
            state,
            status="active",
            trial_end=state.trial_end,
            current_period_start=at("2028-03-31T12:00:00"),
            current_period_end=at(resumed_end),
            billing_cycle_anchor=at("2028-03-31T12:00:00"),
            paid_current_period=True,
        ),
    )
    fixed_clock.advance(at("2028-03-31T12:00:00") - fixed_clock())
    await _send(
        authed_client,
        fake_billing,
        "evt_trial_resumed",
        "customer.subscription.updated",
        {"customer": "cus_monthly"},
    )
    resumed = (await authed_client.get("/api/v1/billing/me")).json()
    assert resumed["subscription"]["current_period_end"] == resumed_end + "Z"
    assert resumed["free_access"] is None
    allowance = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert allowance["trial"] is False and allowance["resets_at"] == "2028-04-30T12:00:00Z"


@pytest.mark.parametrize("seconds, expected", [(0, 200), (-1, 409)])
async def test_annual_combined_horizon_counts_remaining_paid_time_without_consuming(
    authed_client, coupons, db, user, fake_billing, fixed_clock, seconds, expected
):
    target = at("2029-03-01T12:00:00")
    fixed_clock.advance(target - timedelta(days=730) + timedelta(seconds=seconds) - fixed_clock())
    state = await monthly(db, user, fake_billing, fixed_clock)
    fake_billing.set_subscription(
        "cus_monthly",
        replace(
            state,
            interval="year",
            current_period_start=at("2026-12-01T12:00:00"),
            billing_cycle_anchor=at("2026-12-01T12:00:00"),
            current_period_end=at("2027-12-01T12:00:00"),
        ),
    )
    created = await coupons("--months", "15")
    preview = await authed_client.post(PREVIEW, json={"code": created["code"]})
    assert preview.status_code == expected, preview.text
    if expected == 200:
        assert preview.json()["ends_at"] == "2029-03-01T12:00:00Z"
        redeemed = await authed_client.post(REDEEM, json=confirmation(preview.json()))
        assert redeemed.json()["status"] == "completed"
    else:
        assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0
        assert fake_billing.deferrals == []


@pytest.mark.parametrize(
    "interval, start, end, free_end",
    [
        ("month", "2028-01-31T12:00:00", "2028-02-29T12:00:00", "2028-03-31T12:00:00Z"),
        ("year", "2028-02-29T12:00:00", "2029-02-28T12:00:00", "2029-03-29T12:00:00Z"),
    ],
)
async def test_paid_boundaries_use_original_anchor_in_short_months(
    authed_client, coupons, db, user, fake_billing, fixed_clock, interval, start, end, free_end
):
    fixed_clock.advance(at(start) + timedelta(days=2) - fixed_clock())
    state = await monthly(db, user, fake_billing, fixed_clock)
    fake_billing.set_subscription(
        "cus_monthly",
        replace(
            state,
            interval=interval,
            current_period_start=at(start),
            billing_cycle_anchor=at(start),
            current_period_end=at(end),
        ),
    )
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    assert offer["ends_at"] == free_end
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "completed"


async def test_trial_cancellation_preserves_trial_free_and_known_end_after_purge(
    authed_client, coupons, db, user, fake_billing, fixed_clock, sells_top_ups
):
    state = await monthly(db, user, fake_billing, fixed_clock)
    end = fixed_clock() + timedelta(days=5)
    state = replace(
        state,
        status="trialing",
        paid_current_period=False,
        trial_start=fixed_clock() - timedelta(days=5),
        trial_end=end,
        current_period_start=fixed_clock() - timedelta(days=5),
        current_period_end=end,
        billing_cycle_anchor=end,
    )
    fake_billing.set_subscription("cus_monthly", state)
    created = await coupons("--months", "6")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "completed"
    cancellation = await authed_client.post("/api/v1/billing/cancel-renewal")
    assert cancellation.status_code == 200
    assert cancellation.json()["subscription"]["cancel_at"] == offer["ends_at"]
    original = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert original["trial"] and original["may_buy_top_up"] is False
    fixed_clock.advance(timedelta(days=100))
    await coupons(command="purge")
    saved = await db.scalar(
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    assert state.trial_start is not None
    assert (
        saved is not None
        and saved.preserved_trial is True
        and saved.paid_start == state.trial_start.replace(tzinfo=None)
    )
    current = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert current["trial"] is False and current["generations"]["limit"] == 500
    fixed_clock.advance(at(offer["ends_at"].removesuffix("Z")) - fixed_clock())
    assert (await authed_client.get("/api/v1/billing/me")).json()["subscribed"] is False
    fixed_clock.advance(timedelta(days=91))
    await db.rollback()
    await coupons(command="purge")
    assert (await authed_client.get("/api/v1/billing/me")).json()["subscribed"] is False
    await db.refresh(saved)
    assert (
        saved.preserved_trial,
        saved.paid_start,
        saved.paid_end,
        saved.paid_anchor,
        saved.paid_allowance,
    ) == (None, None, None, None, None)


async def test_definite_trial_refusal_keeps_original_trial_actions_and_does_not_consume(
    authed_client, coupons, db, user, fake_billing, fixed_clock, sells_top_ups
):
    state = await monthly(db, user, fake_billing, fixed_clock)
    end = fixed_clock() + timedelta(days=5)
    fake_billing.set_subscription(
        "cus_monthly",
        replace(
            state,
            status="trialing",
            paid_current_period=False,
            trial_start=fixed_clock() - timedelta(days=5),
            trial_end=end,
            current_period_start=fixed_clock() - timedelta(days=5),
            current_period_end=end,
            billing_cycle_anchor=end,
        ),
    )
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    fake_billing.fail_on.add("refuse_deferral")
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "refused"
    allowance = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert allowance["trial"] is True
    assert allowance["generations"]["limit"] == 125
    assert allowance["way_out"] == "subscribe_now"
    assert allowance["may_buy_top_up"] is False
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0
