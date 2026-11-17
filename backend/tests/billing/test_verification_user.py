from datetime import datetime, timedelta
from io import StringIO

import pytest
from sqlalchemy import event

from pumpkit.auth.models import User
from pumpkit.billing.runtime_config import run_cli
from pumpkit.core.config import settings
from tests.billing.paid_signups import SIGNUPS, open_paid_signup, redeem_coupon
from tests.billing.test_billing import BILLING_ME, CHECKOUT, CHECKOUT_MONTHLY
from tests.billing.test_billing import monthly_plan as monthly_plan
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_top_ups import ACCEPTANCE, TOP_UP_CHECKOUT
from tests.billing.test_top_ups import sells_top_ups as sells_top_ups
from tests.billing.test_trial_eligibility import sign_in


@pytest.fixture(autouse=True)
def billing_clock(fake_billing, fixed_clock):
    fake_billing.clock = fixed_clock


async def test_only_the_selected_user_can_start_checkout_during_the_pause(
    authed_client, user, new_browser, sign_in_for_test, fake_billing, monkeypatch
):
    other = new_browser()
    signed = await sign_in_for_test(other, "other@example.com")
    other.headers["Authorization"] = f"Bearer {signed.access_token}"
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", user.id)

    selected = (await authed_client.get(BILLING_ME)).json()
    assert selected["purchases_available"] is True
    assert selected["may_subscribe"] is True
    assert selected["trial_days"] == 7
    assert selected["subscribed"] is False
    others = await other.get(BILLING_ME)
    assert others.json()["purchases_available"] is False
    assert user.id not in others.text
    bypass = await other.post(
        CHECKOUT,
        json={**CHECKOUT_MONTHLY, "verification_user": True, "user_id": user.id},
        headers={"X-Billing-Verification-User": user.id},
    )
    assert bypass.status_code == 422
    refused = await other.post(CHECKOUT, json=CHECKOUT_MONTHLY)
    assert refused.status_code == 503
    assert refused.json()["code"] == "BILLING_PURCHASES_PAUSED"
    assert fake_billing.checkouts == []

    opened = await authed_client.post(CHECKOUT, json=CHECKOUT_MONTHLY)
    assert opened.status_code == 200, opened.text
    assert len(fake_billing.checkouts) == 1
    assert (await authed_client.get(BILLING_ME)).json()["subscribed"] is False
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", None)
    assert (await authed_client.get(BILLING_ME)).json()["purchases_available"] is False
    assert (await authed_client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 503
    assert len(fake_billing.checkouts) == 1


async def test_mutable_profile_and_admin_status_do_not_transfer_the_selection(
    authed_client, user, db, new_browser, sign_in_for_test, monkeypatch
):
    other_user = User(
        email="different@example.com",
        display_name="Other",
        x_user_id="2002",
        x_handle=user.x_handle,
        is_admin=True,
    )
    db.add(other_user)
    await db.commit()
    other = new_browser()
    signed = await sign_in_for_test(other, other_user.email)
    other.headers["Authorization"] = f"Bearer {signed.access_token}"
    other_user.email = user.email
    await db.commit()
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", user.id)
    assert (await authed_client.get(BILLING_ME)).json()["purchases_available"] is True
    assert (await other.get(BILLING_ME)).json()["purchases_available"] is False
    assert (await other.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 503
    user.email = "changed@example.com"
    user.x_handle = "changed"
    await db.commit()
    assert (await authed_client.get(BILLING_ME)).json()["purchases_available"] is True
    assert (await other.get(BILLING_ME)).json()["purchases_available"] is False


@pytest.mark.parametrize("invalid", ["missing", "non_x"])
async def test_invalid_selection_stays_closed_without_breaking_billing_reads(
    authed_client, user, db, monkeypatch, invalid
):
    selected_id = user.id
    if invalid == "non_x":
        user.x_user_id = None
        await db.commit()
    else:
        selected_id = "user_01ARZ3NDEKTSV4RRFFQ69G5FAV"
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", selected_id)
    assert (await authed_client.get(BILLING_ME)).json()["purchases_available"] is False
    assert (await authed_client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 503


async def test_selected_user_keeps_terms_and_top_up_eligibility_rules(
    authed_client, user, fake_billing, monkeypatch, sells_top_ups
):
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", user.id)
    refused = await authed_client.post(CHECKOUT, json={**CHECKOUT_MONTHLY, "accepted_terms": False})
    assert refused.status_code == 422
    ineligible = await authed_client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)
    assert ineligible.status_code == 409
    assert fake_billing.checkouts == []
    assert fake_billing.top_up_checkouts == []


async def test_selected_user_can_buy_a_top_up_without_changing_free_access_or_balance(
    authed_client, coupons, sells_top_ups, user, fake_billing, monkeypatch
):
    free = await redeem_coupon(authed_client, coupons)
    before = (await authed_client.get("/api/v1/usage")).json()
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", user.id)
    assert (await authed_client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 409
    assert (
        await authed_client.post(TOP_UP_CHECKOUT, json={**ACCEPTANCE, "accepted_terms": False})
    ).status_code == 422
    assert (await authed_client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)).status_code == 200
    assert len(fake_billing.top_up_checkouts) == 1
    assert (await authed_client.get("/api/v1/usage")).json() == before
    me = (await authed_client.get(BILLING_ME)).json()
    assert me["free_access"]["ends_at"] == free["ends_at"]
    assert me["subscription"] is None
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", None)
    assert (await authed_client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)).status_code == 503
    assert len(fake_billing.top_up_checkouts) == 1


async def test_selected_user_cannot_bypass_an_unknown_accepted_signup_dispatch(
    authed_client, coupons, user, fake_billing, monkeypatch
):
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", user.id)
    fake_billing.fail_on.add("create_paid_signup_checkout")
    free, request, opened = await open_paid_signup(authed_client, coupons)
    assert opened["status"] == "pending" and opened["url"] is None
    before = (await authed_client.get("/api/v1/usage")).json()
    fake_billing.fail_on.clear()
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", None)
    waiting = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert waiting.json()["url"] is None
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", user.id)
    recovered = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert recovered.json()["status"] == "pending"
    assert recovered.json()["url"] is None
    assert recovered.json()["first_payment_at"] == free["ends_at"]
    assert fake_billing.paid_signup_checkouts == {}
    assert (await authed_client.get("/api/v1/usage")).json() == before
    assert (await authed_client.get(BILLING_ME)).json()["subscription"] is None


async def test_another_selected_user_does_not_unlock_top_ups_or_new_signup(
    authed_client, coupons, sells_top_ups, new_browser, sign_in_for_test, fake_billing, monkeypatch
):
    await redeem_coupon(authed_client, coupons)
    preview = (
        await authed_client.post(SIGNUPS + "/preview", json={"plan_key": "pumpkit_pro_monthly"})
    ).json()
    other = new_browser()
    signed = await sign_in_for_test(other, "selected-other@example.com")
    other.headers["Authorization"] = f"Bearer {signed.access_token}"
    selected_id = (await other.get("/api/v1/users/me")).json()["id"]
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", selected_id)
    assert (await authed_client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)).status_code == 503
    request = {
        "operation_id": "11111111-1111-4111-8111-111111111111",
        "revision": preview["revision"],
        "terms_version": preview["terms_version"],
        "accepted_terms": True,
        "requested_immediate_start": True,
        "approved_specific_clauses": True,
        "language": "en",
    }
    assert (await authed_client.post(SIGNUPS, json=request)).status_code == 503
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).status_code == 404
    assert fake_billing.top_up_checkouts == []
    assert fake_billing.paid_signup_checkouts == {}


async def test_selected_signup_still_requires_current_terms_and_minimum_future_date(
    authed_client, coupons, user, fake_billing, monkeypatch, fixed_clock
):
    free = await redeem_coupon(authed_client, coupons)
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", user.id)
    offer = (
        await authed_client.post(SIGNUPS + "/preview", json={"plan_key": "pumpkit_pro_monthly"})
    ).json()
    refused = await authed_client.post(
        SIGNUPS,
        json={
            "operation_id": "11111111-1111-4111-8111-111111111111",
            "revision": offer["revision"],
            "terms_version": offer["terms_version"],
            "accepted_terms": False,
            "requested_immediate_start": True,
            "approved_specific_clauses": True,
            "language": "en",
        },
    )
    assert refused.status_code == 422
    end = datetime.fromisoformat(free["ends_at"].replace("Z", "+00:00"))
    fixed_clock.advance(end - fixed_clock() - timedelta(hours=48))
    assert (
        await authed_client.post(SIGNUPS + "/preview", json={"plan_key": "pumpkit_pro_monthly"})
    ).status_code == 409
    assert fake_billing.paid_signup_checkouts == {}


async def test_recreated_x_account_does_not_inherit_the_deleted_users_exception(
    new_browser, fake_x_publisher, monkeypatch, db_engine, db_session_maker
):
    @event.listens_for(db_engine.sync_engine, "connect")
    def enforce_cascades(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    browser = new_browser()
    original = await sign_in(browser, fake_x_publisher)
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", original["id"])
    assert (await browser.get(BILLING_ME)).json()["purchases_available"] is True
    deleted = await browser.request("DELETE", "/api/v1/users/me", json={"handle": "ada"})
    assert deleted.status_code == 204, deleted.text
    recreated = await sign_in(browser, fake_x_publisher)
    assert recreated["id"] != original["id"]
    assert (await browser.get(BILLING_ME)).json()["purchases_available"] is False
    assert (await browser.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 503
    out, err = StringIO(), StringIO()
    assert await run_cli([], sessions=db_session_maker, stdout=out, stderr=err) == 1
    assert '"valid": false' in out.getvalue()
    assert original["id"] not in out.getvalue() + err.getvalue()
