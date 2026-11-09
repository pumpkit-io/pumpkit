from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_monthly_coupons import monthly
from tests.billing.test_top_ups import ACCEPTANCE, TOP_UP_CHECKOUT, _send
from tests.billing.test_top_ups import sells_top_ups as sells_top_ups


@pytest.mark.parametrize("status", ["active", "trialing"])
async def test_known_cancellation_does_not_restore_access_or_billing_actions_after_purge(
    authed_client, coupons, db, user, fake_billing, fixed_clock, sells_top_ups, status
):
    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "completed"
    assert (await authed_client.post("/api/v1/billing/cancel-renewal")).status_code == 200
    deferred = (await fake_billing.list_subscriptions(customer_id="cus_monthly"))[0]
    fake_billing.set_subscription("cus_monthly", replace(deferred, status=status))
    await _send(
        authed_client,
        fake_billing,
        "evt_cancelled_stale_status",
        "customer.subscription.updated",
        {"customer": "cus_monthly"},
    )
    target = datetime.fromisoformat(offer["ends_at"].replace("Z", "+00:00"))
    fixed_clock.advance(target - timedelta(seconds=1) - fixed_clock())
    assert (await authed_client.get("/api/v1/billing/me")).json()["subscribed"] is True
    usage = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert usage["may_buy_top_up"] is True
    fixed_clock.advance(timedelta(seconds=1))
    assert (await authed_client.get("/api/v1/billing/me")).json()["subscribed"] is False
    assert (await authed_client.get("/api/v1/usage")).status_code == 403
    assert (await authed_client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)).status_code == 409
    assert (await authed_client.post("/api/v1/billing/subscribe-now")).status_code == 409
    fixed_clock.advance(timedelta(days=90))
    await coupons(command="purge")
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).status_code == 404
    for _ in range(2):
        me = (await authed_client.get("/api/v1/billing/me")).json()
        assert me["subscribed"] is False
        assert me["free_access"] is None
        assert me["subscription"]["cancel_at"] == offer["ends_at"]
        assert (await authed_client.get("/api/v1/onboarding")).json()["next_step"] == "paywall"
        assert (await authed_client.get("/api/v1/posts")).status_code == 403
        assert (
            await authed_client.post("/api/v1/posts", json={"brief": "No expired access"})
        ).status_code == 403
        assert (await authed_client.get("/api/v1/usage")).status_code == 403
        assert (await authed_client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)).status_code == 409
        assert (await authed_client.post("/api/v1/billing/subscribe-now")).status_code == 409
        await coupons(command="purge")
    assert fake_billing.top_up_checkouts == []
    assert fake_billing.ended_trials == []
