import asyncio
from io import StringIO

import pytest
from sqlalchemy import select

from pumpkit.account_deletion import run_cli as delete_cli
from pumpkit.auth.models import User
from tests.billing.postgres.test_coupon_contention import blocked_requests, wait_for_locks
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
    assert all(r.json()["status"] in {"pending", "completed"} for r in results[:2])
    assert (await authed_client.get(CHANGES + "/" + request["operation_id"])).json()[
        "status"
    ] == "completed"
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


@pytest.mark.parametrize("replay_error", ["plan_change_in_progress", "refuse_plan_change"])
async def test_independent_replays_keep_guard_until_delayed_original_price_write_is_observed(
    db_engine,
    db_session_maker,
    authed_client,
    coupons,
    user,
    db,
    fake_billing,
    fixed_clock,
    file_storage,
    replay_error,
):
    free = await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    code = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    fake_billing.delay_plan_changes = True
    assert (await authed_client.post(CHANGES, json=request)).json()["status"] == "pending"
    fake_billing.fail_on.add(replay_error)

    async def delete():
        return await delete_cli(
            ["--user-id", user.id],
            sessions=db_session_maker,
            gateway=fake_billing,
            storage=file_storage,
            stdout=StringIO(),
            stderr=StringIO(),
        )

    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == user.id).with_for_update())
        tasks = [
            asyncio.create_task(authed_client.get(CHANGES + "/" + request["operation_id"]))
            for _ in range(2)
        ]
        tasks.append(
            asyncio.create_task(
                authed_client.post(
                    REDEEM, json={**confirmation(offer), "operation_id": "pg-guarded-coupon-0001"}
                )
            )
        )
        tasks.append(asyncio.create_task(delete()))
        results = await blocked_requests(db_engine, control, tasks, 4)
    assert all(r.json()["status"] == "pending" for r in results[:2])
    assert results[2].status_code == 409
    assert results[3] == 1
    assert (await coupons(code["id"], command="inspect"))["redeemed_count"] == 0
    assert fake_billing.plan_changes == []
    fake_billing.fail_on.clear()
    fake_billing.complete_pending_plan_change(next(iter(fake_billing.pending_plan_changes)))
    await _send(
        authed_client,
        fake_billing,
        "evt_pg_late_price",
        "customer.subscription.updated",
        {"customer": user.stripe_customer_id},
    )
    assert (await authed_client.get(CHANGES + "/" + request["operation_id"])).json()[
        "status"
    ] == "completed"
    assert len(fake_billing.plan_changes) == 1
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["future_plan"]["first_payment_at"] == free["ends_at"]


async def test_new_recovery_owner_cannot_leave_stale_first_dispatch_free_to_terminally_refuse(
    db_engine, authed_client, coupons, user, db, fake_billing, fixed_clock, monkeypatch
):
    await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    entered, release = asyncio.Event(), asyncio.Event()
    live_read = fake_billing.list_subscriptions
    pause = True

    async def slow_confirmation_read(**kwargs):
        nonlocal pause
        if pause:
            pause = False
            entered.set()
            await asyncio.wait_for(release.wait(), 10)
        return await live_read(**kwargs)

    monkeypatch.setattr(fake_billing, "list_subscriptions", slow_confirmation_read)
    fake_billing.fail_on.add("refuse_plan_change")
    confirming = asyncio.create_task(authed_client.post(CHANGES, json=request))
    await asyncio.wait_for(entered.wait(), 10)
    recovering = asyncio.create_task(authed_client.get(CHANGES + "/" + request["operation_id"]))
    try:
        await wait_for_locks(db_engine, 1)
    finally:
        release.set()
    results = await asyncio.wait_for(asyncio.gather(confirming, recovering), 10)
    assert all(r.status_code == 200 and r.json()["status"] == "pending" for r in results)
    assert (await authed_client.get("/api/v1/billing/me")).json()[
        "pending_plan_change_id"
    ] == request["operation_id"]
    fake_billing.fail_on.clear()
    assert (await authed_client.get(CHANGES + "/" + request["operation_id"])).json()[
        "status"
    ] == "completed"
    assert len(fake_billing.plan_changes) == 1
