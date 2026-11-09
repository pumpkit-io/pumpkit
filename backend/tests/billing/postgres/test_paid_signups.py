import asyncio

import pytest
from sqlalchemy import select

from pumpkit.account_deletion import delete_account
from pumpkit.auth.models import User
from pumpkit.core.errors import ConflictError
from tests.billing.postgres.test_coupon_contention import blocked_requests
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_paid_signups import SIGNUPS, _open
from tests.billing.test_top_ups import _send

pytestmark = pytest.mark.postgres


async def test_independent_duplicate_recovery_and_provider_nudge_create_one_subscription(
    db_engine, db_session_maker, authed_client, coupons, user, fake_billing
):
    free, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
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
    assert all(r.json()["status"] == "completed" for r in results[:2])
    assert len(fake_billing.paid_signups_created) == 1
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["free_access"]["ends_at"] == free["ends_at"]


async def test_deletion_and_recovery_share_user_lock_and_cannot_orphan_future_payment(
    db_engine, db_session_maker, authed_client, coupons, user, fake_billing
):
    _, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])

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
    fake_billing.complete_paid_signup_setup(opened["session_id"])
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
