import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from pumpkit.auth.models import User
from pumpkit.billing.models import Coupon
from tests.billing.postgres.test_coupon_contention import wait_for_locks
from tests.billing.test_billing import CHECKOUT, CHECKOUT_MONTHLY
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_coupon_x_identity_migration import (
    test_coupon_x_identity_migration_preserves_email_claims_and_reverses as test_coupon_x_identity_migration_preserves_email_claims_and_reverses,
)
from tests.billing.test_coupon_x_identity_migration import (
    test_downgrade_cannot_erase_retained_x_coupon_claims as test_downgrade_cannot_erase_retained_x_coupon_claims,
)
from tests.billing.test_coupon_x_identity_migration import user as user
from tests.billing.test_top_up_account_deletion import remove_user
from tests.billing.test_trial_eligibility import sign_in
from tests.billing.test_trial_eligibility import sign_in_app as sign_in_app
from tests.billing.test_trial_eligibility import trial_app as trial_app
from tests.billing.test_trial_eligibility import trial_browser as trial_browser

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("same_x", [False, True])
async def test_parallel_x_claims_exclude_shared_email_and_same_account(
    trial_app, trial_browser, fake_x_publisher, coupons, db_session_maker, db_engine, same_x
):
    await sign_in(trial_browser, fake_x_publisher)
    async with AsyncClient(
        transport=ASGITransport(app=trial_app), base_url="http://test"
    ) as second:
        await sign_in(second, fake_x_publisher, x_id="1001" if same_x else "2002")
        created = await coupons("--max-redemptions", "5")
        offers = [
            (await browser.post(PREVIEW, json={"code": created["code"]})).json()
            for browser in (trial_browser, second)
        ]
        async with db_session_maker() as control:
            await control.scalar(select(Coupon).where(Coupon.id == created["id"]).with_for_update())
            tasks = [
                asyncio.create_task(
                    browser.post(REDEEM, json=confirmation(offer, f"parallel-x-{i:08}"))
                )
                for i, (browser, offer) in enumerate(zip((trial_browser, second), offers))
            ]
            try:
                await wait_for_locks(db_engine, 2)
            finally:
                await control.commit()
            responses = await asyncio.wait_for(asyncio.gather(*tasks), 10)
        assert sorted(response.status_code for response in responses) == [200, 409]
        assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 1


async def test_x_redemption_then_waiting_deletion_preserves_claim_and_trial_exclusion(
    trial_browser,
    fake_x_publisher,
    coupons,
    db_session_maker,
    db_engine,
    fake_billing,
    file_storage,
):
    original = await sign_in(trial_browser, fake_x_publisher)
    created = await coupons("--max-redemptions", "5")
    offer = (await trial_browser.post(PREVIEW, json={"code": created["code"]})).json()
    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == original["id"]).with_for_update())
        redeem = asyncio.create_task(trial_browser.post(REDEEM, json=confirmation(offer)))
        await wait_for_locks(db_engine, 1)
        deletion = asyncio.create_task(
            remove_user(db_session_maker, fake_billing, file_storage, original["id"])
        )
        try:
            await wait_for_locks(db_engine, 2)
        finally:
            await control.commit()
        response, (status, error) = await asyncio.wait_for(asyncio.gather(redeem, deletion), 10)
    assert response.status_code == 200
    assert status == 0, error
    await sign_in(trial_browser, fake_x_publisher, email="changed@example.org")
    assert (await trial_browser.post(PREVIEW, json={"code": created["code"]})).status_code == 409
    assert (await trial_browser.get("/api/v1/billing/me")).json()["trial_days"] is None


async def test_confirming_coupon_serializes_with_introductory_checkout(
    trial_browser,
    fake_x_publisher,
    coupons,
    db_session_maker,
    db_engine,
    fake_billing,
    file_storage,
):
    original = await sign_in(trial_browser, fake_x_publisher)
    created = await coupons("--max-redemptions", "5")
    offer = (await trial_browser.post(PREVIEW, json={"code": created["code"]})).json()
    async with db_session_maker() as control:
        await control.scalar(select(Coupon).where(Coupon.id == created["id"]).with_for_update())
        redeem = asyncio.create_task(trial_browser.post(REDEEM, json=confirmation(offer)))
        await wait_for_locks(db_engine, 1)
        checkout = asyncio.create_task(trial_browser.post(CHECKOUT, json=CHECKOUT_MONTHLY))
        try:
            await wait_for_locks(db_engine, 2)
        finally:
            await control.commit()
        response, refused = await asyncio.wait_for(asyncio.gather(redeem, checkout), 10)
    assert response.status_code == 200
    assert refused.status_code == 409
    assert fake_billing.checkouts == []
    status, error = await remove_user(db_session_maker, fake_billing, file_storage, original["id"])
    assert status == 0, error
    await sign_in(trial_browser, fake_x_publisher, email="changed@example.org")
    assert (await trial_browser.get("/api/v1/billing/me")).json()["trial_days"] is None
