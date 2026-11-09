from datetime import timedelta
from io import StringIO

import pytest

from pumpkit.account_deletion import run_cli
from pumpkit.billing.gateway import TopUpPurchase
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_free_access_top_ups import redeem
from tests.billing.test_top_ups import ACCEPTANCE, TOP_UP_CHECKOUT
from tests.billing.test_top_ups import sells_top_ups as sells_top_ups


async def remove_user(sessions, fake_billing, file_storage, user_id):
    error = StringIO()
    status = await run_cli(
        ["--user-id", user_id],
        sessions=sessions,
        gateway=fake_billing,
        storage=file_storage,
        stdout=StringIO(),
        stderr=error,
    )
    return status, error.getvalue()


@pytest.mark.parametrize(
    "processing,resolution",
    [(False, "paid"), (False, "expired"), (True, "paid"), (True, "canceled")],
)
async def test_cardless_top_up_checkout_blocks_deletion_without_expiring_it(
    client,
    coupons,
    sells_top_ups,
    db_session_maker,
    user,
    fake_billing,
    file_storage,
    processing,
    fixed_clock,
    resolution,
):
    await redeem(client, coupons)
    assert (await client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)).status_code == 200
    customer_id = fake_billing.top_up_checkouts[0].customer_id
    if processing:
        fake_billing.set_top_up_payment_pending(
            customer_id=customer_id, checkout_session_id="cs_top_up_fake_1"
        )
    status, error = await remove_user(db_session_maker, fake_billing, file_storage, user.id)
    assert status == 1
    assert "checkout" in error
    assert (await client.get("/api/v1/billing/me")).status_code == 200
    assert fake_billing.expired_checkouts == []
    if resolution == "paid":
        fake_billing.set_top_up(
            customer_id,
            TopUpPurchase(
                checkout_session_id="cs_top_up_fake_1", paid_at=fixed_clock(), reversed=False
            ),
        )
    elif resolution == "expired":
        await fake_billing.expire_open_checkouts(customer_id=customer_id)
    else:
        fake_billing.set_top_up_payment_canceled(checkout_session_id="cs_top_up_fake_1")
    assert (await remove_user(db_session_maker, fake_billing, file_storage, user.id))[0] == 0


async def test_user_deleted_during_price_read_cannot_create_a_top_up_checkout(
    client, coupons, sells_top_ups, db_session_maker, user, fake_billing, file_storage, monkeypatch
):
    await redeem(client, coupons)
    original = fake_billing.get_one_off_price

    async def price_after_deletion(key):
        assert (await remove_user(db_session_maker, fake_billing, file_storage, user.id))[0] == 0
        return await original(key)

    monkeypatch.setattr(fake_billing, "get_one_off_price", price_after_deletion)
    response = await client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)
    assert response.status_code == 403, response.text
    assert fake_billing.top_up_checkouts == []
    assert fake_billing.customers_created == []


async def test_free_access_expiring_while_customer_is_created_cannot_start_checkout(
    client, coupons, sells_top_ups, fake_billing, fixed_clock, monkeypatch
):
    await redeem(client, coupons)
    original = fake_billing.create_customer

    async def create_after_expiry(**kwargs):
        customer = await original(**kwargs)
        fixed_clock.advance(timedelta(days=100))
        return customer

    monkeypatch.setattr(fake_billing, "create_customer", create_after_expiry)
    response = await client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)
    assert response.status_code == 409, response.text
    assert fake_billing.top_up_checkouts == []
