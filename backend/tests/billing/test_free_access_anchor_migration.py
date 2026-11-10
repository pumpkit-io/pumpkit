import pytest

from alembic import command
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.migrations import migrate


async def test_anchor_upgrade_preserves_existing_benefit_and_replay(client, coupons, db_engine):
    created = await coupons("--months", "1")
    offer = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    request = confirmation(offer)
    result = (await client.post(REDEEM, json=request)).json()
    before = (await client.get("/api/v1/billing/me")).json()
    usage = (await client.get("/api/v1/usage")).json()
    await migrate(db_engine, lambda config: command.stamp(config, "head"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0045"))
    await migrate(db_engine, lambda config: command.upgrade(config, "head"))
    assert (await client.get("/api/v1/billing/me")).json() == before
    assert (await client.get("/api/v1/usage")).json() == usage
    assert (await client.post(REDEEM, json=request)).json() == result
    another = await coupons("--months", "1")
    appended = (await client.post(PREVIEW, json={"code": another["code"]})).json()
    assert appended["starts_at"] == result["ends_at"]
    assert (
        await client.post(REDEEM, json=confirmation(appended, "after-anchor-upgrade"))
    ).status_code == 200


@pytest.fixture
async def user(legacy_user):
    return legacy_user
