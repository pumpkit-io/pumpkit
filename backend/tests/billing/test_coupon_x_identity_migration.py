import pytest
import sqlalchemy as sa

from alembic import command
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_x_coupon_identity import coupons as coupons
from tests.billing.test_x_coupon_identity import sign_in
from tests.billing.test_x_coupon_identity import sign_in_app as sign_in_app
from tests.billing.test_x_coupon_identity import trial_app as trial_app
from tests.billing.test_x_coupon_identity import trial_browser as trial_browser
from tests.migrations import migrate


async def test_coupon_x_identity_migration_preserves_email_claims_and_reverses(
    db_engine, authed_client, coupons
):

    created = await coupons()
    preview = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(preview))).status_code == 200
    await migrate(db_engine, lambda config: command.stamp(config, "0057"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0056"))
    async with db_engine.connect() as connection:
        before = (
            await connection.execute(sa.text("SELECT id,key_id,fingerprint FROM coupon_claims"))
        ).all()
    await migrate(db_engine, lambda config: command.upgrade(config, "0057"))
    async with db_engine.connect() as connection:
        after = (
            await connection.execute(sa.text("SELECT id,key_id,fingerprint FROM coupon_claims"))
        ).all()
        assert before == after
        assert await connection.scalar(sa.text("SELECT x_fingerprint FROM coupon_claims")) is None


async def test_downgrade_cannot_erase_retained_x_coupon_claims(
    db_engine, trial_browser, fake_x_publisher, coupons
):

    await sign_in(trial_browser, fake_x_publisher)
    created = await coupons()
    preview = (await trial_browser.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await trial_browser.post(REDEEM, json=confirmation(preview))).status_code == 200
    await migrate(db_engine, lambda config: command.stamp(config, "0057"))
    with pytest.raises(RuntimeError, match="Retained X coupon claims"):
        await migrate(db_engine, lambda config: command.downgrade(config, "0056"))
