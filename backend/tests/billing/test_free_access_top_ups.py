from datetime import timedelta

import pytest
from sqlalchemy import select

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.billing.gateway import TopUpPurchase
from pumpkit.billing.models import FreeAccess, Subscription
from pumpkit.core.config import settings
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_top_ups import (
    ACCEPTANCE,
    TOP_UP_CHECKOUT,
    _send,
)
from tests.billing.test_top_ups import (
    sells_top_ups as sells_top_ups,
)
from tests.positioning.positioning import save_positioning


async def redeem(client, coupons):
    created = await coupons()
    preview = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    response = await client.post(REDEEM, json=confirmation(preview))
    assert response.status_code == 200, response.text
    return response.json()


async def test_current_cardless_free_access_buys_normal_top_up_without_recurring_commitment(
    client, coupons, sells_top_ups, fake_billing, fixed_clock, monkeypatch
):
    benefit = await redeem(client, coupons)
    monkeypatch.setattr(settings, "COUPONS_ENABLED", False)
    refused = await client.post(TOP_UP_CHECKOUT, json={**ACCEPTANCE, "accepted_terms": False})
    assert refused.status_code == 422
    assert fake_billing.top_up_checkouts == []
    response = await client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)
    assert response.status_code == 200, response.text
    assert len(fake_billing.top_up_checkouts) == 1
    assert fake_billing.top_up_checkouts[0].price_id == "price_top_up"
    me = (await client.get("/api/v1/billing/me")).json()
    assert me["subscription"] is None
    assert me["free_access"]["ends_at"] == benefit["ends_at"]
    assert fake_billing.checkouts == []
    usage = (await client.get("/api/v1/usage")).json()["allowance"]
    assert usage["may_buy_top_up"] is True
    assert usage["way_out"] == "top_up"
    assert usage["trial"] is False
    fixed_clock.advance(timedelta(days=100))
    assert (await client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)).status_code == 409


async def test_usage_and_limit_actions_follow_the_injected_current_free_period(
    client, coupons, sells_top_ups, fixed_clock
):
    fixed_clock.advance(timedelta(days=800))
    await redeem(client, coupons)
    usage = (await client.get("/api/v1/usage")).json()["allowance"]
    assert usage["may_buy_top_up"] is True
    assert usage["way_out"] == "top_up"


@pytest.mark.parametrize("status", ["trialing", "past_due"])
async def test_queued_free_time_does_not_unlock_checkout_or_projected_usage_action(
    client,
    coupons,
    sells_top_ups,
    db,
    user,
    fixed_clock,
    fake_billing,
    status,
    connect_x,
    post_with,
):
    await redeem(client, coupons)
    grant = (await db.execute(select(FreeAccess))).scalar_one()
    grant.starts_at = fixed_clock() + timedelta(days=7)
    grant.ends_at = fixed_clock() + timedelta(days=97)
    grant.calendar_anchor = grant.starts_at
    grant.coverage_starts_at = grant.starts_at
    grant.allowance = {**grant.allowance, "x_posts": 1}
    db.add(
        Subscription(
            user_id=user.id,
            stripe_subscription_id="sub_queued",
            stripe_customer_id="cus_queued",
            status=status,
            stripe_created_at=fixed_clock(),
            trial_start=fixed_clock(),
            trial_end=fixed_clock() + timedelta(days=7),
        )
    )
    await db.commit()
    response = await client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)
    assert response.status_code == 409
    assert fake_billing.top_up_checkouts == []
    expected = "subscribe_now" if status == "trialing" else "update_payment"
    assert (await client.get("/api/v1/usage")).json()["allowance"]["way_out"] == expected
    future = await client.get("/api/v1/usage", params={"at": grant.starts_at.isoformat()})
    assert future.json()["allowance"]["may_buy_top_up"] is False
    await connect_x()
    scheduled = await client.post(
        "/api/v1/scheduled-posts",
        json={
            "post_id": await post_with("One", "Two"),
            "publish_at": (fixed_clock() + timedelta(days=8))
            .replace(second=0, microsecond=0)
            .isoformat(),
        },
    )
    assert scheduled.status_code == 409, scheduled.text
    assert scheduled.json()["way_out"] is None


async def test_current_free_time_allows_top_up_when_provider_reports_trialing(
    client, coupons, sells_top_ups, db, user, fixed_clock
):
    await redeem(client, coupons)
    db.add(
        Subscription(
            user_id=user.id,
            stripe_subscription_id="sub_deferred",
            stripe_customer_id="cus_deferred",
            status="trialing",
            stripe_created_at=fixed_clock(),
            trial_start=fixed_clock(),
            trial_end=fixed_clock() + timedelta(days=90),
        )
    )
    await db.commit()
    assert (await client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)).status_code == 200
    usage = (await client.get("/api/v1/usage")).json()["allowance"]
    assert usage["trial"] is False
    assert usage["way_out"] == "top_up"
    assert usage["generations"]["limit"] == 500


@pytest.mark.parametrize("event", ["charge.refunded", "charge.dispute.created"])
async def test_free_access_spends_existing_packs_allowance_first_and_keeps_reversal_rules(
    client,
    coupons,
    sells_top_ups,
    db,
    user,
    fixed_clock,
    fake_billing,
    monkeypatch,
    fake_x_reader,
    fake_llm,
    event,
):
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 2)
    user.stripe_customer_id = "cus_saved"
    await db.commit()
    for session, days in [("cs_expired", 366), ("cs_soon", 10), ("cs_later", 1)]:
        fake_billing.set_top_up(
            "cus_saved",
            TopUpPurchase(
                checkout_session_id=session,
                paid_at=fixed_clock() - timedelta(days=days),
                reversed=False,
                charge_id="ch_" + session,
            ),
        )
    assert (
        await _send(
            client,
            fake_billing,
            "evt_saved",
            "checkout.session.completed",
            {"customer": "cus_saved"},
        )
    ).status_code == 200
    await redeem(client, coupons)
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(post_id="example", text="A useful note", posted_at=fixed_clock())
    ]
    await save_positioning(client)
    assert (
        await client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    ).status_code == 201
    for i in range(4):
        fake_llm.replies = [{"post": "finished"}]
        response = await client.post("/api/v1/posts", json={"brief": "Write something useful"})
        assert response.status_code == 201, response.text
        usage = (await client.get("/api/v1/usage")).json()["allowance"]
        assert usage["generations"]["used"] == min(i + 1, 2)
        assert [p["generations_left"] for p in usage["top_ups"]] == (
            [1, 1] if i < 2 else [0, 1] if i == 2 else [0, 0]
        )
    refused = await client.post("/api/v1/posts", json={"brief": "No room left"})
    assert refused.status_code == 409
    assert refused.json()["way_out"] == "top_up"
    fake_billing.set_top_up(
        "cus_saved",
        TopUpPurchase(
            checkout_session_id="cs_new",
            paid_at=fixed_clock(),
            reversed=False,
            charge_id="ch_new",
        ),
    )
    assert (
        await _send(
            client, fake_billing, "evt_new", "checkout.session.completed", {"customer": "cus_saved"}
        )
    ).status_code == 200
    fake_billing.set_top_up(
        "cus_saved",
        TopUpPurchase(
            checkout_session_id="cs_new",
            paid_at=fixed_clock(),
            reversed=True,
            charge_id="ch_new",
        ),
    )
    assert (
        await _send(
            client,
            fake_billing,
            "evt_reverse",
            event,
            {"customer": "cus_saved", "charge": "ch_new"},
        )
    ).status_code == 200
    assert [
        p["generations_left"]
        for p in (await client.get("/api/v1/usage")).json()["allowance"]["top_ups"]
    ] == [0, 0]
    assert (await client.get("/api/v1/billing/me")).json()["subscription"] is None
