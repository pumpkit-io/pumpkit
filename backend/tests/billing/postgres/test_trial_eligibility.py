import asyncio

import pytest
from sqlalchemy import select

from pumpkit.auth.models import User
from tests.billing.postgres.test_coupon_contention import wait_for_locks
from tests.billing.test_billing import CHECKOUT, CHECKOUT_MONTHLY
from tests.billing.test_top_up_account_deletion import remove_user
from tests.billing.test_trial_eligibility import (
    BILLING_ME,
    ended_trial,
    sign_in,
)
from tests.billing.test_trial_eligibility import (
    sign_in_app as sign_in_app,
)
from tests.billing.test_trial_eligibility import (
    test_lost_historical_key_does_not_block_settled_deletion_or_restore_trial as test_lost_historical_key_does_not_block_settled_deletion_or_restore_trial,
)
from tests.billing.test_trial_eligibility import (
    trial_app as trial_app,
)
from tests.billing.test_trial_eligibility import (
    trial_browser as trial_browser,
)
from tests.billing.test_trial_eligibility import (
    trial_keys as trial_keys,
)
from tests.billing.test_trial_eligibility_migration import (
    test_downgrade_cannot_erase_retained_trial_eligibility as test_downgrade_cannot_erase_retained_trial_eligibility,
)
from tests.billing.test_trial_eligibility_migration import (
    test_empty_eligibility_migration_can_be_reversed_without_changing_users as test_empty_eligibility_migration_can_be_reversed_without_changing_users,
)

pytestmark = pytest.mark.postgres


async def test_deletion_winning_before_checkout_keeps_history_and_refuses_stale_user(
    trial_browser,
    fake_x_publisher,
    fake_billing,
    fixed_clock,
    db_engine,
    db_session_maker,
    file_storage,
):
    original = await sign_in(trial_browser, fake_x_publisher)
    assert (await trial_browser.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 200
    customer = fake_billing.checkouts[-1].customer_id
    fake_billing.set_subscription(customer, ended_trial(fixed_clock))
    await fake_billing.expire_open_checkouts(customer_id=customer)
    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == original["id"]).with_for_update())
        deletion = asyncio.create_task(
            remove_user(db_session_maker, fake_billing, file_storage, original["id"])
        )
        await wait_for_locks(db_engine, 1)
        checkout = asyncio.create_task(trial_browser.post(CHECKOUT, json=CHECKOUT_MONTHLY))
        try:
            await wait_for_locks(db_engine, 2)
        finally:
            await control.commit()
        (status, error), response = await asyncio.wait_for(asyncio.gather(deletion, checkout), 10)
    assert status == 0, error
    assert response.status_code == 403
    assert len(fake_billing.checkouts) == 1

    await sign_in(trial_browser, fake_x_publisher, email="changed@example.org")
    assert (await trial_browser.get(BILLING_ME)).json()["trial_days"] is None


async def test_deletion_waits_for_first_checkout_then_refuses_unsettled_work(
    trial_browser,
    fake_x_publisher,
    fake_billing,
    db_engine,
    db_session_maker,
    file_storage,
    monkeypatch,
):
    original_user = await sign_in(trial_browser, fake_x_publisher)
    entered, release = asyncio.Event(), asyncio.Event()
    original = fake_billing.create_subscription_checkout

    async def paused(**kwargs):
        entered.set()
        await asyncio.wait_for(release.wait(), 10)
        return await original(**kwargs)

    monkeypatch.setattr(fake_billing, "create_subscription_checkout", paused)
    checkout = asyncio.create_task(trial_browser.post(CHECKOUT, json=CHECKOUT_MONTHLY))
    await asyncio.wait_for(entered.wait(), 10)
    deletion = asyncio.create_task(
        remove_user(db_session_maker, fake_billing, file_storage, original_user["id"])
    )
    try:
        await wait_for_locks(db_engine, 1)
    finally:
        release.set()
    response, (status, error) = await asyncio.wait_for(asyncio.gather(checkout, deletion), 10)
    assert response.status_code == 200
    assert status == 1
    assert "checkout" in error
    assert [checkout.trial_period_days for checkout in fake_billing.checkouts] == [7]
    assert (await trial_browser.get(BILLING_ME)).status_code == 200
