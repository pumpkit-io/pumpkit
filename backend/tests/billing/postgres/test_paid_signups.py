import asyncio
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from pumpkit.account_deletion import delete_account
from pumpkit.auth.models import User
from pumpkit.billing.allowance import months_after
from pumpkit.billing.gateway import BillingProviderError
from pumpkit.core.config import settings
from pumpkit.core.errors import ConflictError
from tests.billing.postgres.test_coupon_contention import blocked_requests
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_paid_signups import SIGNUPS, _open
from tests.billing.test_paid_signups import billing_clock as billing_clock
from tests.billing.test_top_ups import _send

pytestmark = pytest.mark.postgres


async def test_independent_duplicate_recovery_and_provider_nudge_create_one_subscription(
    db_engine, db_session_maker, authed_client, coupons, user, fake_billing
):
    free, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_checkout(opened["session_id"])
    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == user.id).with_for_update())
        tasks = [
            asyncio.create_task(authed_client.get(SIGNUPS + "/" + request["operation_id"]))
            for _ in range(2)
        ]
        tasks.append(
            asyncio.create_task(
                _send(
                    authed_client,
                    fake_billing,
                    "evt_pg_setup",
                    "checkout.session.completed",
                    {"customer": "cus_fake_1"},
                )
            )
        )
        results = await blocked_requests(db_engine, control, tasks, 3)
    assert all(r.json()["status"] in {"pending", "completed"} for r in results[:2])
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "completed"
    assert len(fake_billing.paid_signups_created) == 1
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["free_access"]["ends_at"] == free["ends_at"]


async def test_deletion_and_recovery_share_user_lock_and_cannot_orphan_future_payment(
    db_engine, db_session_maker, authed_client, coupons, user, fake_billing
):
    _, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_checkout(opened["session_id"])

    async def delete():
        async with db_session_maker() as deletion_db:
            with pytest.raises(ConflictError):
                await delete_account(deletion_db, fake_billing, user_id=user.id)

    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == user.id).with_for_update())
        tasks = [
            asyncio.create_task(delete()),
            asyncio.create_task(authed_client.get(SIGNUPS + "/" + request["operation_id"])),
        ]
        results = await blocked_requests(db_engine, control, tasks, 2)
    assert results[1].json()["status"] == "completed"
    assert len(fake_billing.paid_signups_created) == 1


async def test_cancellation_racing_recovery_removes_future_payment_and_retains_free_time(
    db_engine, db_session_maker, authed_client, coupons, user, fake_billing
):
    free, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_checkout(opened["session_id"])
    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == user.id).with_for_update())
        tasks = [
            asyncio.create_task(authed_client.get(SIGNUPS + "/" + request["operation_id"])),
            asyncio.create_task(
                authed_client.post(SIGNUPS + "/" + request["operation_id"] + "/cancel")
            ),
        ]
        await blocked_requests(db_engine, control, tasks, 2)
    states = await fake_billing.list_subscriptions(customer_id="cus_fake_1")
    assert all(s.status == "canceled" for s in states)
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscribed"] is True
    assert me["free_access"]["ends_at"] == free["ends_at"]


@pytest.mark.parametrize("cancel", [True, False])
async def test_late_provider_write_cannot_escape_pending_cancellation_or_deletion_lock(
    db_engine, db_session_maker, authed_client, coupons, user, fake_billing, fixed_clock, cancel
):
    free, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_checkout(opened["session_id"], listed=False)
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "pending"
    if not cancel:
        target = datetime.fromisoformat(free["ends_at"].replace("Z", "+00:00"))
        fixed_clock.advance(target - fixed_clock())

    async def delete():
        async with db_session_maker() as deletion_db:
            with pytest.raises(ConflictError):
                await delete_account(deletion_db, fake_billing, user_id=user.id)

    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == user.id).with_for_update())
        action = (
            authed_client.post(SIGNUPS + "/" + request["operation_id"] + "/cancel")
            if cancel
            else authed_client.get(SIGNUPS + "/" + request["operation_id"])
        )
        tasks = [asyncio.create_task(action), asyncio.create_task(delete())]
        results = await blocked_requests(db_engine, control, tasks, 2)
    assert results[0].json()["status"] == "pending"
    fake_billing.list_paid_signup_subscription(opened["session_id"])
    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == user.id).with_for_update())
        tasks = [
            asyncio.create_task(authed_client.get(SIGNUPS + "/" + request["operation_id"])),
            asyncio.create_task(
                _send(
                    authed_client,
                    fake_billing,
                    "evt_pg_late",
                    "customer.subscription.created",
                    {"customer": "cus_fake_1"},
                )
            ),
        ]
        results = await blocked_requests(db_engine, control, tasks, 2)
    states = await fake_billing.list_subscriptions(customer_id="cus_fake_1")
    # Without a cancellation, the Checkout the User completed in time stands.
    assert results[0].json()["status"] == ("refused" if cancel else "completed")
    assert len(states) == 1 and states[0].status == ("canceled" if cancel else "active")


@pytest.mark.parametrize("after_mutation", [True, False])
async def test_completed_cancellation_checkpoint_keeps_paid_access_and_excludes_deletion_on_uncertainty(
    db_engine,
    db_session_maker,
    authed_client,
    coupons,
    user,
    fake_billing,
    fixed_clock,
    monkeypatch,
    after_mutation,
):
    free, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_checkout(opened["session_id"])
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "completed"
    target = datetime.fromisoformat(free["ends_at"].replace("Z", "+00:00"))
    fixed_clock.advance(target - timedelta(seconds=1) - fixed_clock())
    original_list = fake_billing.list_subscriptions
    original_cancel = fake_billing.cancel_subscription
    crossed = False
    raised = False

    async def crossing(*, customer_id):
        nonlocal crossed
        states = await original_list(customer_id=customer_id)
        if not crossed:
            crossed = True
            fixed_clock.advance(timedelta(seconds=2))
            fake_billing.set_subscription(
                customer_id,
                replace(
                    states[0],
                    status="active",
                    current_period_start=target,
                    current_period_end=months_after(target, 1),
                    paid_current_period=True,
                ),
            )
        return await original_list(customer_id=customer_id)

    async def uncertain_cancel(*, subscription_id):
        nonlocal raised
        if not raised:
            raised = True
            if after_mutation:
                await original_cancel(subscription_id=subscription_id)
            raise BillingProviderError("Uncertain provider cancellation")
        await original_cancel(subscription_id=subscription_id)

    monkeypatch.setattr(fake_billing, "list_subscriptions", crossing)
    monkeypatch.setattr(fake_billing, "cancel_subscription", uncertain_cancel)
    assert (await authed_client.post(SIGNUPS + "/" + request["operation_id"] + "/cancel")).json()[
        "status"
    ] == "pending"
    fake_billing.fail_on.add("list_subscriptions")

    async def delete():
        async with db_session_maker() as deletion_db:
            with pytest.raises(ConflictError):
                await delete_account(deletion_db, fake_billing, user_id=user.id)

    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == user.id).with_for_update())
        tasks = [
            asyncio.create_task(authed_client.get(SIGNUPS + "/" + request["operation_id"])),
            asyncio.create_task(delete()),
        ]
        results = await blocked_requests(db_engine, control, tasks, 2)
    assert results[0].json()["status"] == "pending"
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["pending_paid_signup_id"] == request["operation_id"] and me["subscribed"] is True
    assert datetime.fromisoformat(
        me["subscription"]["paid_through"].replace("Z", "+00:00")
    ) == months_after(target, 1)
    fake_billing.fail_on.clear()
    monkeypatch.setattr(settings, "COUPONS_ENABLED", False)
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "refused"
    assert len(fake_billing.cancelled_subscriptions) == 1
    assert (await authed_client.get("/api/v1/usage")).json()["allowance"]["generations"][
        "limit"
    ] == 500
