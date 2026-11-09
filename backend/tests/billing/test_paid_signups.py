from dataclasses import replace
from datetime import datetime, timedelta
from io import StringIO

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from pumpkit.account_deletion import delete_account
from pumpkit.billing.gateway import Plan
from pumpkit.billing.paid_signup_recovery import run_cli
from pumpkit.core.config import settings
from pumpkit.core.errors import ConflictError
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_monthly_coupons import monthly
from tests.billing.test_top_ups import _send

SIGNUPS = "/api/v1/billing/paid-signups"


@pytest.mark.parametrize("plan_key", ["pumpkit_pro_monthly", "pumpkit_pro_yearly"])
async def test_explicit_future_signup_preserves_free_allowance_and_exact_payment_date(
    authed_client, coupons, fake_billing, fixed_clock, plan_key, monkeypatch
):
    monkeypatch.setattr(
        settings, "BILLING_PLAN_KEYS", ["pumpkit_pro_monthly", "pumpkit_pro_yearly"]
    )
    fake_billing.plans.append(
        Plan("pumpkit_pro_yearly", "price_yearly", "Pro", 20000, "eur", "year", 1)
    )
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).status_code == 200
    before = (await authed_client.get("/api/v1/usage")).json()
    preview = await authed_client.post(SIGNUPS + "/preview", json={"plan_key": plan_key})
    assert preview.status_code == 200, preview.text
    paid = preview.json()
    assert paid["first_payment_at"] == offer["ends_at"]
    request = {
        "operation_id": "11111111-1111-4111-8111-111111111111",
        "revision": paid["revision"],
        "terms_version": paid["terms_version"],
        "accepted_terms": True,
        "requested_immediate_start": True,
        "approved_specific_clauses": True,
        "language": "en",
    }
    opened = await authed_client.post(SIGNUPS, json=request)
    assert opened.status_code == 200, opened.text
    assert opened.json()["status"] == "pending"
    assert opened.json()["url"]
    assert fake_billing.checkouts == []
    assert (await authed_client.get("/api/v1/usage")).json() == before
    fake_billing.complete_paid_signup_setup(opened.json()["session_id"])
    await _send(
        authed_client,
        fake_billing,
        "evt_setup",
        "checkout.session.completed",
        {"customer": fake_billing.customers_created[0] and "cus_fake_1"},
    )
    result = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert result.json()["status"] == "completed", result.text
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["free_access"]["ends_at"] == offer["ends_at"]
    assert me["subscription"]["plan_key"] == plan_key
    assert me["subscription"]["current_period_end"] == offer["ends_at"]
    assert me["subscription"]["introductory_trial_end"] is None
    assert (await authed_client.get("/api/v1/usage")).json() == before
    assert (await authed_client.post(SIGNUPS, json=request)).json()["status"] == "completed"
    assert len(fake_billing.paid_signups_created) == 1


async def _open(client, coupons, plan_key="pumpkit_pro_monthly"):
    created = await coupons("--months", "1")
    free = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await client.post(REDEEM, json=confirmation(free))).status_code == 200
    preview = await client.post(SIGNUPS + "/preview", json={"plan_key": plan_key})
    assert preview.status_code == 200, preview.text
    paid = preview.json()
    request = {
        "operation_id": "11111111-1111-4111-8111-111111111111",
        "revision": paid["revision"],
        "terms_version": paid["terms_version"],
        "accepted_terms": True,
        "requested_immediate_start": True,
        "approved_specific_clauses": True,
        "language": "en",
    }
    result = await client.post(SIGNUPS, json=request)
    assert result.status_code == 200, result.text
    return free, request, result.json()


async def test_later_coupon_extends_arranged_payment_without_inventing_paid_or_trial_coverage(
    authed_client, coupons, fake_billing, db
):
    free, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "completed"
    coupon = await coupons("--months", "2")
    preview = await authed_client.post(PREVIEW, json={"code": coupon["code"]})
    assert preview.status_code == 200, preview.text
    result = await authed_client.post(
        REDEEM, json=confirmation(preview.json(), operation="later-coupon-0001")
    )
    assert result.status_code == 200 and result.json()["status"] == "completed", result.text
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["paid_through"] is None
    assert me["subscription"]["introductory_trial_end"] is None
    assert me["subscription"]["current_period_end"] == preview.json()["ends_at"]
    assert me["free_access"]["starts_at"] == free["starts_at"]
    assert me["free_access"]["months"] == 3
    cancelled = await authed_client.post("/api/v1/billing/cancel-renewal")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["subscription"]["cancel_at"] == preview.json()["ends_at"]
    assert cancelled.json()["free_access"]["ends_at"] == preview.json()["ends_at"]


@pytest.mark.parametrize("remaining", [172799, 172800, 172801, 1])
async def test_near_end_signup_keeps_exact_date_without_checkout_48_hour_floor(
    authed_client, coupons, fake_billing, fixed_clock, remaining
):
    free, request, opened = await _open(authed_client, coupons)
    end = datetime.fromisoformat(free["ends_at"].replace("Z", "+00:00"))
    fixed_clock.advance(end - timedelta(seconds=remaining) - fixed_clock())
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    result = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert result.json()["status"] == "completed", result.text
    assert result.json()["first_payment_at"] == free["ends_at"]
    states = await fake_billing.list_subscriptions(customer_id="cus_fake_1")
    assert states[0].trial_end == end
    assert states[0].billing_cycle_anchor == end


@pytest.mark.parametrize("completion_after_expiry", [False, True])
async def test_expired_free_end_never_silently_charges_or_changes_paid_date(
    authed_client, coupons, fake_billing, fixed_clock, completion_after_expiry
):
    free, request, opened = await _open(authed_client, coupons)
    if not completion_after_expiry:
        fake_billing.complete_paid_signup_setup(opened["session_id"])
    end = datetime.fromisoformat(free["ends_at"].replace("Z", "+00:00"))
    fixed_clock.advance(end - fixed_clock())
    if completion_after_expiry:
        fake_billing.complete_paid_signup_setup(opened["session_id"])
    result = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert result.json()["status"] == "refused"
    assert result.json()["first_payment_at"] == free["ends_at"]
    assert fake_billing.paid_signups_created == []
    assert (await authed_client.get("/api/v1/billing/me")).json()["subscribed"] is False


@pytest.mark.parametrize(
    "failure", ["after_create_paid_signup_setup", "create_paid_signup", "after_create_paid_signup"]
)
async def test_provider_uncertainty_reconciles_after_key_retention_and_without_browser(
    authed_client, coupons, fake_billing, fixed_clock, db_session_maker, failure
):
    fake_billing.fail_on.add(failure)
    free, request, opened = await _open(authed_client, coupons)
    assert opened["status"] == "pending"
    setup = next(iter(fake_billing.paid_signup_setups.values()))
    fake_billing.complete_paid_signup_setup(setup.id)
    if failure != "after_create_paid_signup_setup":
        assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
            "status"
        ] == "pending"
    fixed_clock.advance(timedelta(hours=25))
    fake_billing.fail_on.clear()
    out = StringIO()
    assert (
        await run_cli(
            ["recover"],
            sessions=db_session_maker,
            gateway=fake_billing,
            clock=fixed_clock,
            stdout=out,
        )
        == 0
    )
    assert "completed" in out.getvalue()
    assert len(fake_billing.paid_signup_setups) == 1
    assert len(fake_billing.paid_signups_created) == 1
    for event_id in ["evt_paid_first", "evt_paid_first", "evt_late_setup"]:
        await _send(
            authed_client,
            fake_billing,
            event_id,
            "checkout.session.completed",
            {"customer": "cus_fake_1"},
        )
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "completed"
    assert len(fake_billing.paid_signups_created) == 1
    assert (await authed_client.get("/api/v1/billing/me")).json()["free_access"]["ends_at"] == free[
        "ends_at"
    ]


async def test_open_signup_blocks_billing_coupon_and_deletion_until_cancelled_without_losing_free_access(
    authed_client, coupons, fake_billing, monkeypatch, db_session_maker, user
):
    free, request, opened = await _open(authed_client, coupons)
    coupon = await coupons("--months", "1")
    assert (await authed_client.post(PREVIEW, json={"code": coupon["code"]})).status_code == 409
    for route in ["/api/v1/billing/portal", "/api/v1/billing/subscribe-now"]:
        assert (await authed_client.post(route)).status_code == 409
    async with db_session_maker() as deletion_db:
        with pytest.raises(ConflictError):
            await delete_account(deletion_db, fake_billing, user_id=user.id)
    monkeypatch.setattr(settings, "COUPONS_ENABLED", False)
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["pending_paid_signup_id"] == request["operation_id"]
    cancelled = await authed_client.post(SIGNUPS + "/" + request["operation_id"] + "/cancel")
    assert cancelled.json()["status"] == "refused", cancelled.text
    assert fake_billing.paid_signups_created == []
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["pending_paid_signup_id"] is None
    assert me["free_access"]["ends_at"] == free["ends_at"]
    assert me["subscribed"] is True


async def test_saved_customer_and_old_subscription_never_authorize_a_future_signup(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    state = await monthly(db, user, fake_billing, fixed_clock)
    fake_billing.set_subscription(
        "cus_monthly",
        replace(
            state,
            status="canceled",
            current_period_end=fixed_clock() - timedelta(days=1),
            paid_current_period=False,
        ),
    )
    await _send(
        authed_client,
        fake_billing,
        "evt_old",
        "customer.subscription.deleted",
        {"customer": "cus_monthly"},
    )
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).status_code == 200
    assert fake_billing.paid_signups_created == []
    assert fake_billing.paid_signup_setups == {}
    assert (await authed_client.get("/api/v1/billing/me")).json()["may_arrange_paid_signup"] is True
    paid = (
        await authed_client.post(SIGNUPS + "/preview", json={"plan_key": "pumpkit_pro_monthly"})
    ).json()
    missing = await authed_client.post(
        SIGNUPS,
        json={
            "operation_id": "saved-card-operation",
            "revision": paid["revision"],
            "terms_version": paid["terms_version"],
            "language": "en",
        },
    )
    assert missing.status_code == 422
    assert fake_billing.paid_signup_setups == {}


async def test_customer_response_lost_before_local_id_is_recovered_from_provider_metadata(
    authed_client, coupons, fake_billing, fixed_clock
):
    fake_billing.fail_on.add("after_create_customer")
    _, request, opened = await _open(authed_client, coupons)
    assert opened["status"] == "pending" and opened["url"] is None
    fixed_clock.advance(timedelta(hours=25))
    fake_billing.fail_on.clear()
    result = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert result.json()["status"] == "refused"
    assert len(fake_billing.customers_created) == 1
    assert fake_billing.paid_signups_created == []


async def test_provider_success_database_commit_failure_is_recovered_without_another_subscription(
    authed_client, coupons, fake_billing, db_session_maker, fixed_clock, monkeypatch
):
    _, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    failed = False

    def fail_commit(session):
        nonlocal failed
        if fake_billing.paid_signups_created and not failed:
            failed = True
            raise RuntimeError("Simulated local commit failure")

    event.listen(Session, "before_commit", fail_commit)
    try:
        result = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
        assert result.status_code == 500
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert failed
    monkeypatch.setattr(settings, "COUPONS_ENABLED", False)
    assert (
        await run_cli(
            ["recover"],
            sessions=db_session_maker,
            gateway=fake_billing,
            clock=fixed_clock,
            stdout=StringIO(),
        )
        == 0
    )
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "completed"
    assert len(fake_billing.paid_signups_created) == 1
