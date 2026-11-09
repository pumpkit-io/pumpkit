import asyncio

import pytest
from sqlalchemy import select

from pumpkit.auth.models import User
from tests.billing.postgres.test_coupon_contention import blocked_requests
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_plan_changes import CHANGES, deferred, proposed_change
from tests.billing.test_plan_changes import both_plans as both_plans
from tests.billing.test_top_ups import _send

pytestmark = pytest.mark.postgres


async def test_independent_duplicate_change_and_webhook_keep_one_future_price(
    db_engine, db_session_maker, authed_client, coupons, user, db, fake_billing, fixed_clock
):
    free = await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == user.id).with_for_update())
        tasks = [asyncio.create_task(authed_client.post(CHANGES, json=request)) for _ in range(2)]
        tasks.append(
            asyncio.create_task(
                _send(
                    authed_client,
                    fake_billing,
                    "evt_pg_plan",
                    "customer.subscription.updated",
                    {"customer": user.stripe_customer_id},
                )
            )
        )
        results = await blocked_requests(db_engine, control, tasks, 3)
    assert all(r.json()["status"] == "completed" for r in results[:2])
    assert len(fake_billing.plan_changes) == 1
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["future_plan"]["first_payment_at"] == free["ends_at"]
    assert me["subscription"]["plan_key"] == "pumpkit_pro_annual"


async def test_competing_coupon_and_price_change_preserve_date_without_consuming_stale_offer(
    db_engine, db_session_maker, authed_client, coupons, user, db, fake_billing, fixed_clock
):
    free = await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    code = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == user.id).with_for_update())
        tasks = [
            asyncio.create_task(authed_client.post(CHANGES, json=request)),
            asyncio.create_task(
                authed_client.post(
                    REDEEM, json={**confirmation(offer), "operation_id": "competing-coupon-0001"}
                )
            ),
        ]
        results = await blocked_requests(db_engine, control, tasks, 2)
    assert sorted(r.status_code for r in results) == [200, 409]
    successful = results[0].status_code == 200
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["free_access"]["ends_at"] == (free["ends_at"] if successful else offer["ends_at"])
    assert (await coupons(code["id"], command="inspect"))["redeemed_count"] == (
        0 if successful else 1
    )
    assert len(fake_billing.plan_changes) == (1 if successful else 0)


async def test_cancel_and_change_race_never_reactivates_payment(
    db_engine, db_session_maker, authed_client, coupons, user, db, fake_billing, fixed_clock
):
    free = await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == user.id).with_for_update())
        tasks = [
            asyncio.create_task(authed_client.post(CHANGES, json=request)),
            asyncio.create_task(authed_client.post("/api/v1/billing/cancel-renewal")),
        ]
        results = await blocked_requests(db_engine, control, tasks, 2)
    assert results[0].status_code in {200, 409}
    if results[1].status_code == 409:
        assert (await authed_client.post("/api/v1/billing/cancel-renewal")).status_code == 200
    else:
        assert results[1].status_code == 200
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["cancel_at"] == free["ends_at"]
    assert me["free_access"]["ends_at"] == free["ends_at"]
    assert me["future_plan"] is None
