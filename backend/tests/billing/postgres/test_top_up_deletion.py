import asyncio

import pytest

from tests.billing.postgres.test_coupon_contention import wait_for_locks
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_free_access_top_ups import redeem
from tests.billing.test_top_up_account_deletion import remove_user
from tests.billing.test_top_ups import ACCEPTANCE, TOP_UP_CHECKOUT
from tests.billing.test_top_ups import sells_top_ups as sells_top_ups

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("saved_customer", [False, True])
async def test_deletion_waits_for_top_up_creation_then_refuses_pending_checkout(
    authed_client,
    coupons,
    sells_top_ups,
    user,
    db,
    db_engine,
    db_session_maker,
    fake_billing,
    file_storage,
    monkeypatch,
    saved_customer,
):
    client = authed_client
    await redeem(client, coupons)
    if saved_customer:
        user.stripe_customer_id = "cus_saved"
        await db.commit()
    entered, release = asyncio.Event(), asyncio.Event()
    original = fake_billing.create_top_up_checkout

    async def paused(**kwargs):
        entered.set()
        await asyncio.wait_for(release.wait(), 10)
        return await original(**kwargs)

    monkeypatch.setattr(fake_billing, "create_top_up_checkout", paused)
    checkout = asyncio.create_task(client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE))
    await asyncio.wait_for(entered.wait(), 10)
    deletion = asyncio.create_task(
        remove_user(db_session_maker, fake_billing, file_storage, user.id)
    )
    try:
        await wait_for_locks(db_engine, 1)
    finally:
        release.set()
    response, (status, error) = await asyncio.wait_for(asyncio.gather(checkout, deletion), 10)
    assert response.status_code == 200, response.text
    assert status == 1
    assert "checkout" in error
    assert (await client.get("/api/v1/billing/me")).status_code == 200
    assert len(fake_billing.top_up_checkouts) == 1
    assert fake_billing.expired_checkouts == []


async def test_deletion_winning_first_customer_commit_prevents_stale_user_checkout(
    authed_client,
    coupons,
    sells_top_ups,
    user,
    db_engine,
    db_session_maker,
    fake_billing,
    file_storage,
    monkeypatch,
):
    client = authed_client
    await redeem(client, coupons)
    original = fake_billing.create_customer
    deletions = []

    async def queued_deletion(**kwargs):
        customer = await original(**kwargs)
        deletions.append(
            asyncio.create_task(remove_user(db_session_maker, fake_billing, file_storage, user.id))
        )
        await wait_for_locks(db_engine, 1)
        return customer

    monkeypatch.setattr(fake_billing, "create_customer", queued_deletion)
    response = await asyncio.wait_for(client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE), 10)
    assert (await asyncio.wait_for(deletions[0], 10))[0] == 0
    assert response.status_code == 403, response.text
    assert fake_billing.top_up_checkouts == []
    assert len(fake_billing.customers_created) == 1
    assert (await client.get("/api/v1/billing/me")).status_code == 401
