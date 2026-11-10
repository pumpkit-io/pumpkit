import json
from datetime import timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from pumpkit.auth.models import User
from pumpkit.billing.models import TrialEligibility
from pumpkit.core.config import settings
from tests.billing.test_coupon_preview import KEYS
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_monthly_coupons import monthly
from tests.billing.test_top_up_account_deletion import remove_user
from tests.billing.test_trial_eligibility import (
    enforce_account_cascades as enforce_account_cascades,
)
from tests.billing.test_trial_eligibility import sign_in
from tests.billing.test_trial_eligibility import sign_in_app as sign_in_app
from tests.billing.test_trial_eligibility import trial_app as trial_app
from tests.billing.test_trial_eligibility import trial_browser as trial_browser


async def test_x_claim_survives_changed_email_and_recreation(
    trial_browser, fake_x_publisher, coupons, db_session_maker, fake_billing, file_storage
):
    original = await sign_in(trial_browser, fake_x_publisher)
    created = await coupons("--max-redemptions", "5")
    preview = (await trial_browser.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await trial_browser.post(REDEEM, json=confirmation(preview))).status_code == 200
    await sign_in(trial_browser, fake_x_publisher, email="changed@example.org")
    refused = await trial_browser.post(PREVIEW, json={"code": created["code"]})
    assert refused.status_code == 409
    assert "already redeemed" in refused.json()["detail"]
    assert (
        await trial_browser.post(REDEEM, json=confirmation(preview, "changed-email-0002"))
    ).status_code == 409
    status, error = await remove_user(db_session_maker, fake_billing, file_storage, original["id"])
    assert status == 0, error
    recreated = await sign_in(trial_browser, fake_x_publisher, email="third@example.org")
    assert recreated["id"] != original["id"]
    assert (await trial_browser.post(PREVIEW, json={"code": created["code"]})).status_code == 409
    assert (await trial_browser.get("/api/v1/billing/me")).json()["trial_days"] is None


async def test_confirmed_x_email_controls_recipient_and_shared_email_claims(
    trial_browser, fake_x_publisher, coupons
):
    await sign_in(trial_browser, fake_x_publisher, email="old@example.com")
    created = await coupons("--recipient", "ADA@EXAMPLE.COM", "--max-redemptions", "5")
    assert (await trial_browser.post(PREVIEW, json={"code": created["code"]})).status_code == 409
    await sign_in(trial_browser, fake_x_publisher, email="ada@example.com")
    preview = (await trial_browser.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await trial_browser.post(REDEEM, json=confirmation(preview))).status_code == 200
    await sign_in(trial_browser, fake_x_publisher, x_id="2002", email="ADA@example.com")
    refused = await trial_browser.post(PREVIEW, json={"code": created["code"]})
    assert refused.status_code == 409
    assert "already redeemed" in refused.json()["detail"]
    different = await coupons("--recipient", "ada@example.com")
    preview = (await trial_browser.post(PREVIEW, json={"code": different["code"]})).json()
    assert (await trial_browser.post(REDEEM, json=confirmation(preview))).status_code == 200


@pytest.mark.parametrize("drop_old", [False, True])
async def test_x_claim_matching_follows_coupon_key_rotation(
    trial_browser, fake_x_publisher, coupons, monkeypatch, drop_old
):
    await sign_in(trial_browser, fake_x_publisher)
    created = await coupons("--max-redemptions", "5")
    preview = (await trial_browser.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await trial_browser.post(REDEEM, json=confirmation(preview))).status_code == 200
    await sign_in(trial_browser, fake_x_publisher, email="new@example.org")
    keys = json.loads(KEYS)
    keys["keys"]["v2"] = "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE="
    keys["active"] = "v2"
    if drop_old:
        del keys["keys"]["v1"]
    monkeypatch.setattr(settings, "COUPON_IDENTITY_KEYS", SecretStr(json.dumps(keys)))
    refused = await trial_browser.post(PREVIEW, json={"code": created["code"]})
    assert refused.status_code == (503 if drop_old else 409)


async def test_only_confirmed_benefit_retains_lifetime_trial_exclusion(
    trial_browser, fake_x_publisher, coupons, fixed_clock, db_session_maker, monkeypatch
):
    await sign_in(trial_browser, fake_x_publisher)
    created = await coupons("--max-redemptions", "5")
    preview = (await trial_browser.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await trial_browser.get("/api/v1/billing/me")).json()["trial_days"] == 7
    failed = confirmation(preview)
    failed["accepted_terms"] = False
    assert (await trial_browser.post(REDEEM, json=failed)).status_code == 422
    async with db_session_maker() as db:
        assert list(await db.scalars(select(TrialEligibility))) == []
    assert (await trial_browser.post(REDEEM, json=confirmation(preview))).status_code == 200
    await coupons(created["id"], command="disable")
    fixed_clock.advance(timedelta(days=200))
    await coupons(command="purge")
    async with db_session_maker() as db:
        retained = list(await db.scalars(select(TrialEligibility)))
        assert len(retained) == 1
        assert retained[0].eligible is False
    assert (await trial_browser.get("/api/v1/billing/me")).json()["trial_days"] is None


async def test_unavailable_trial_key_rolls_back_grant_without_consuming_coupon(
    trial_browser, fake_x_publisher, coupons, monkeypatch
):
    await sign_in(trial_browser, fake_x_publisher)
    created = await coupons("--max-redemptions", "5")
    preview = (await trial_browser.post(PREVIEW, json={"code": created["code"]})).json()
    previous = settings.TRIAL_IDENTITY_KEYS
    monkeypatch.setattr(settings, "TRIAL_IDENTITY_KEYS", SecretStr(""))
    refused = await trial_browser.post(REDEEM, json=confirmation(preview))
    assert refused.status_code == 503
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0
    monkeypatch.setattr(settings, "TRIAL_IDENTITY_KEYS", previous)
    assert (await trial_browser.post(REDEEM, json=confirmation(preview))).status_code == 200


async def test_provider_reservation_retains_x_identity_through_recovery(
    trial_browser, fake_x_publisher, coupons, db, fake_billing, fixed_clock, monkeypatch
):
    original = await sign_in(trial_browser, fake_x_publisher)
    user = await db.get(User, original["id"])
    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--max-redemptions", "5")
    preview = (await trial_browser.post(PREVIEW, json={"code": created["code"]})).json()
    fake_billing.fail_on.add("after_defer_renewal")
    response = await trial_browser.post(REDEEM, json=confirmation(preview))
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    await sign_in(trial_browser, fake_x_publisher, email="changed@example.org")
    monkeypatch.setattr(settings, "COUPONS_ENABLED", False)
    fake_billing.fail_on.clear()
    recovered = await trial_browser.get(REDEEM + "/redeem-test-0001")
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "completed"
    monkeypatch.setattr(settings, "COUPONS_ENABLED", True)
    refused = await trial_browser.post(PREVIEW, json={"code": created["code"]})
    assert refused.status_code == 409
    assert "already redeemed" in refused.json()["detail"]
    assert len(fake_billing.deferrals) == 1


async def test_confirmed_benefit_writes_current_trial_key_despite_lost_historical_key(
    trial_browser, fake_x_publisher, coupons, monkeypatch, db_session_maker
):
    await sign_in(trial_browser, fake_x_publisher)
    first = await coupons()
    preview = (await trial_browser.post(PREVIEW, json={"code": first["code"]})).json()
    assert (await trial_browser.post(REDEEM, json=confirmation(preview))).status_code == 200
    await sign_in(trial_browser, fake_x_publisher, x_id="2002", email="grace@example.org")
    second = await coupons()
    preview = (await trial_browser.post(PREVIEW, json={"code": second["code"]})).json()
    monkeypatch.setattr(
        settings,
        "TRIAL_IDENTITY_KEYS",
        SecretStr('{"active":"new","keys":{"new":"MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE="}}'),
    )
    assert (await trial_browser.post(REDEEM, json=confirmation(preview))).status_code == 200
    async with db_session_maker() as db:
        retained = list(await db.scalars(select(TrialEligibility)))
        assert len(retained) == 2
        assert any(record.key_id == "new" and not record.eligible for record in retained)
