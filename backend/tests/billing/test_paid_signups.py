from dataclasses import replace
from datetime import datetime, timedelta
from io import StringIO

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from pumpkit.account_deletion import delete_account
from pumpkit.billing.allowance import months_after, paid_period
from pumpkit.billing.gateway import Plan
from pumpkit.billing.models import FreeAccess, PaidSignup
from pumpkit.billing.paid_signup_recovery import run_cli
from pumpkit.core.config import settings
from pumpkit.core.errors import ConflictError
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_monthly_coupons import monthly
from tests.billing.test_top_ups import _send

SIGNUPS = "/api/v1/billing/paid-signups"


@pytest.fixture(autouse=True)
def billing_clock(fake_billing, fixed_clock):
    fake_billing.clock = fixed_clock


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


@pytest.mark.parametrize("failure", ["after_create_paid_signup_setup", "after_create_paid_signup"])
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


async def test_successful_setup_cannot_subscribe_with_another_customers_payment_method(
    authed_client, coupons, fake_billing
):
    free, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    setup = fake_billing.paid_signup_setups[opened["session_id"]]
    fake_billing.paid_signup_setups[setup.id] = replace(
        setup, payment_method_customer_id="cus_other"
    )
    response = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert response.json()["status"] == "pending"
    assert fake_billing.paid_signups_created == []
    assert (await authed_client.get("/api/v1/billing/me")).json()["free_access"]["ends_at"] == free[
        "ends_at"
    ]


async def test_subsecond_clock_free_access_uses_provider_representable_exact_boundary(
    authed_client, coupons, fake_billing, fixed_clock
):
    fixed_clock.advance(timedelta(microseconds=123456))
    free, request, opened = await _open(authed_client, coupons)
    assert datetime.fromisoformat(free["ends_at"].replace("Z", "+00:00")).microsecond == 0
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    result = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert result.json()["status"] == "completed"
    assert (await authed_client.get("/api/v1/billing/me")).json()["subscription"][
        "current_period_end"
    ] == free["ends_at"]


async def test_existing_fractional_grant_is_never_rounded_or_sent_to_provider(
    authed_client, coupons, fake_billing, fixed_clock, db
):
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).status_code == 200
    legacy = await db.scalar(select(FreeAccess))
    for field in ("starts_at", "ends_at", "calendar_anchor", "coverage_starts_at"):
        setattr(legacy, field, getattr(legacy, field) + timedelta(microseconds=123456))
    await db.commit()
    fixed_clock.advance(timedelta(seconds=1))
    before = (await authed_client.get("/api/v1/billing/me")).json()
    usage = (await authed_client.get("/api/v1/usage")).json()
    response = await authed_client.post(
        SIGNUPS + "/preview", json={"plan_key": "pumpkit_pro_monthly"}
    )
    assert response.status_code == 409 and "represented exactly" in response.json()["detail"]
    assert (await authed_client.get("/api/v1/billing/me")).json()["free_access"] == before[
        "free_access"
    ]
    assert (await authed_client.get("/api/v1/usage")).json() == usage
    assert fake_billing.customers_created == []
    assert fake_billing.paid_signup_setups == {}
    assert fake_billing.paid_signups_created == []


@pytest.mark.parametrize("settled_paid", [True, False])
async def test_later_coupon_after_signup_detail_purge_uses_real_paid_settlement_not_stale_metadata(
    authed_client, coupons, fake_billing, fixed_clock, settled_paid
):
    free, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "completed"
    end = datetime.fromisoformat(free["ends_at"].replace("Z", "+00:00"))
    fixed_clock.advance(end + timedelta(days=91) - fixed_clock())
    await coupons(command="purge")
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).status_code == 404
    state = (await fake_billing.list_subscriptions(customer_id="cus_fake_1"))[0]
    period = paid_period(end, fixed_clock())
    fake_billing.set_subscription(
        "cus_fake_1",
        replace(
            state,
            status="active" if settled_paid else "trialing",
            paid_current_period=settled_paid,
            current_period_start=period.start,
            current_period_end=period.end,
            latest_invoice_status="paid",
        ),
    )
    coupon = await coupons("--months", "1")
    preview = await authed_client.post(PREVIEW, json={"code": coupon["code"]})
    if not settled_paid:
        assert preview.status_code == 409
        assert fake_billing.deferrals == []
        return
    assert preview.status_code == 200, preview.text
    assert datetime.fromisoformat(preview.json()["starts_at"].replace("Z", "+00:00")) == period.end
    result = await authed_client.post(
        REDEEM, json=confirmation(preview.json(), operation="after-signup-purge-0001")
    )
    assert result.status_code == 200 and result.json()["status"] == "completed", result.text
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["paid_through"] == preview.json()["starts_at"]
    assert me["subscription"]["introductory_trial_end"] is None


async def test_current_and_queued_cardless_grants_offer_the_combined_payment_date(
    authed_client, coupons, fake_billing
):
    first = await coupons("--months", "1")
    first_offer = (await authed_client.post(PREVIEW, json={"code": first["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(first_offer))).status_code == 200
    second = await coupons("--months", "2")
    second_offer = (await authed_client.post(PREVIEW, json={"code": second["code"]})).json()
    assert (
        await authed_client.post(
            REDEEM, json=confirmation(second_offer, operation="queued-cardless-0001")
        )
    ).status_code == 200
    usage = (await authed_client.get("/api/v1/usage")).json()
    preview = await authed_client.post(
        SIGNUPS + "/preview", json={"plan_key": "pumpkit_pro_monthly"}
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["first_payment_at"] == second_offer["ends_at"]
    assert (await authed_client.get("/api/v1/usage")).json() == usage
    assert fake_billing.paid_signups_created == []
    paid = preview.json()
    opened = await authed_client.post(
        SIGNUPS,
        json={
            "operation_id": "stacked-paid-signup-0001",
            "revision": paid["revision"],
            "terms_version": paid["terms_version"],
            "accepted_terms": True,
            "requested_immediate_start": True,
            "approved_specific_clauses": True,
            "language": "en",
        },
    )
    assert opened.status_code == 200, opened.text
    fake_billing.complete_paid_signup_setup(opened.json()["session_id"])
    assert (await authed_client.get(SIGNUPS + "/stacked-paid-signup-0001")).json()[
        "status"
    ] == "completed"
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["current_period_end"] == second_offer["ends_at"]
    assert me["free_access"]["months"] == 3
    assert (await authed_client.get("/api/v1/usage")).json() == usage


@pytest.mark.parametrize("cancel", [True, False])
async def test_late_remote_creation_keeps_cancellation_and_expiry_pending_until_proven(
    authed_client, coupons, fake_billing, fixed_clock, db_session_maker, user, cancel
):
    free, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    fake_billing.delay_paid_signup_creation = True
    attempt = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert attempt.json()["status"] == "pending"
    assert len(fake_billing.paid_signup_create_attempts) == 1
    if cancel:
        answer = await authed_client.post(SIGNUPS + "/" + request["operation_id"] + "/cancel")
    else:
        end = datetime.fromisoformat(free["ends_at"].replace("Z", "+00:00"))
        fixed_clock.advance(end - fixed_clock())
        answer = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert answer.json()["status"] == "pending", answer.text
    async with db_session_maker() as deletion_db:
        with pytest.raises(ConflictError):
            await delete_account(deletion_db, fake_billing, user_id=user.id)
    fixed_clock.advance(timedelta(hours=25))
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "pending"
    assert len(fake_billing.paid_signup_create_attempts) == 1
    operation_id = next(iter(fake_billing.pending_paid_signup_creations))
    fake_billing.complete_pending_paid_signup(operation_id)
    await _send(
        authed_client,
        fake_billing,
        "evt_late_remote",
        "customer.subscription.created",
        {"customer": "cus_fake_1"},
    )
    result = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert result.json()["status"] == "refused", result.text
    states = await fake_billing.list_subscriptions(customer_id="cus_fake_1")
    assert len(states) == 1 and states[0].status == "canceled"
    assert len(fake_billing.paid_signup_create_attempts) == 1
    assert len(fake_billing.paid_signups_created) == 1
    if cancel:
        assert (await authed_client.get("/api/v1/billing/me")).json()["free_access"][
            "ends_at"
        ] == free["ends_at"]


@pytest.mark.parametrize(
    "provider_status,expected",
    [("canceled", "refused"), ("incomplete_expired", "refused"), ("incomplete", "pending")],
)
async def test_attributed_unfinished_or_ended_subscription_is_not_confirmed_renewal(
    authed_client, coupons, fake_billing, provider_status, expected
):
    _, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    fake_billing.delay_paid_signup_creation = True
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "pending"
    operation_id = next(iter(fake_billing.pending_paid_signup_creations))
    fake_billing.complete_pending_paid_signup(operation_id)
    state = (await fake_billing.list_subscriptions(customer_id="cus_fake_1"))[0]
    fake_billing.set_subscription("cus_fake_1", replace(state, status=provider_status))
    result = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert result.json()["status"] == expected, result.text
    assert len(fake_billing.paid_signup_create_attempts) == 1


async def test_failed_creation_checkpoint_commit_sends_no_remote_subscription_request(
    authed_client, coupons, fake_billing
):
    _, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    failed = False

    def fail_checkpoint(session):
        nonlocal failed
        if not failed and any(
            isinstance(obj, PaidSignup) and obj.creation_state == "uncertain"
            for obj in session.dirty
        ):
            failed = True
            raise RuntimeError("Checkpoint commit failed before dispatch")

    event.listen(Session, "before_commit", fail_checkpoint)
    try:
        assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).status_code == 500
    finally:
        event.remove(Session, "before_commit", fail_checkpoint)
    assert failed and fake_billing.paid_signup_create_attempts == []
    result = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert result.json()["status"] == "completed"
    assert len(fake_billing.paid_signup_create_attempts) == 1


async def test_crash_after_durable_checkpoint_recovers_with_same_key_inside_retention(
    authed_client, coupons, fake_billing
):
    _, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    failed = False

    def crash_after_checkpoint(session):
        nonlocal failed
        if not failed and any(
            isinstance(obj, PaidSignup) and obj.creation_state == "uncertain"
            for obj in session.identity_map.values()
        ):
            failed = True
            raise RuntimeError("Process stopped after committing dispatch checkpoint")

    event.listen(Session, "after_commit", crash_after_checkpoint)
    try:
        assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).status_code == 500
    finally:
        event.remove(Session, "after_commit", crash_after_checkpoint)
    assert failed and fake_billing.paid_signup_create_attempts == []
    result = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert result.json()["status"] == "completed", result.text
    assert len(fake_billing.paid_signup_create_attempts) == 1
    assert len(fake_billing.paid_signups_created) == 1


async def test_inflight_key_replay_keeps_same_subscription_and_stops_after_retention(
    authed_client, coupons, fake_billing, fixed_clock
):
    _, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    fake_billing.delay_paid_signup_creation = True
    for _ in range(2):
        result = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
        assert result.json()["status"] == "pending"
    assert len(set(fake_billing.paid_signup_create_attempts)) == 1
    assert len(fake_billing.pending_paid_signup_creations) == 1
    fixed_clock.advance(timedelta(hours=25))
    result = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert result.json()["status"] == "pending"
    assert len(fake_billing.paid_signup_create_attempts) == 2
    fake_billing.complete_pending_paid_signup(fake_billing.paid_signup_create_attempts[0])
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "completed"
    assert len(fake_billing.paid_signups_created) == 1


@pytest.mark.parametrize("settled_paid", [True, False])
async def test_late_creation_cancellation_preserves_only_proven_paid_coverage(
    authed_client, coupons, fake_billing, fixed_clock, db_session_maker, user, settled_paid
):
    free, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    fake_billing.delay_paid_signup_creation = True
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "pending"
    target = datetime.fromisoformat(free["ends_at"].replace("Z", "+00:00"))
    fixed_clock.advance(target + timedelta(hours=1) - fixed_clock())
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "pending"
    fake_billing.complete_pending_paid_signup(fake_billing.paid_signup_create_attempts[0])
    state = (await fake_billing.list_subscriptions(customer_id="cus_fake_1"))[0]
    paid_end = state.current_period_end
    if not settled_paid:
        fake_billing.set_subscription(
            "cus_fake_1", replace(state, paid_current_period=False, latest_invoice_status="open")
        )
        fake_billing.unsettled_invoice_customers.add("cus_fake_1")
    result = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert result.json()["status"] == "refused"
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["free_access"] is None
    if settled_paid:
        assert me["subscribed"] is True
        assert (
            datetime.fromisoformat(me["subscription"]["paid_through"].replace("Z", "+00:00"))
            == paid_end
        )
        usage = (await authed_client.get("/api/v1/usage")).json()["allowance"]
        assert usage["generations"]["limit"] == 500
        assert usage["trial"] is False
        assert datetime.fromisoformat(usage["resets_at"].replace("Z", "+00:00")) == paid_end
        fixed_clock.advance(paid_end - fixed_clock())
        assert (await authed_client.get("/api/v1/billing/me")).json()["subscribed"] is False
    else:
        assert me["subscribed"] is False and me["subscription"] is None
        async with db_session_maker() as deletion_db:
            with pytest.raises(ConflictError):
                await delete_account(deletion_db, fake_billing, user_id=user.id)
    assert len(fake_billing.paid_signup_create_attempts) == 1


@pytest.mark.parametrize("interval", ["month", "year"])
@pytest.mark.parametrize("settles_during", ["list", "cancel"])
@pytest.mark.parametrize("settled_paid", [True, False])
async def test_cancellation_across_first_payment_preserves_final_proven_coverage(
    authed_client,
    coupons,
    fake_billing,
    fixed_clock,
    monkeypatch,
    db_session_maker,
    user,
    interval,
    settles_during,
    settled_paid,
):
    monkeypatch.setattr(
        settings, "BILLING_PLAN_KEYS", ["pumpkit_pro_monthly", "pumpkit_pro_yearly"]
    )
    fake_billing.plans.append(
        Plan("pumpkit_pro_yearly", "price_yearly", "Pro", 20000, "eur", "year", 1)
    )
    free, request, opened = await _open(
        authed_client,
        coupons,
        "pumpkit_pro_yearly" if interval == "year" else "pumpkit_pro_monthly",
    )
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    fake_billing.delay_paid_signup_creation = True
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "pending"
    target = datetime.fromisoformat(free["ends_at"].replace("Z", "+00:00"))
    fixed_clock.advance(target - timedelta(seconds=1) - fixed_clock())
    operation_id = fake_billing.paid_signup_create_attempts[0]
    original_list = fake_billing.list_subscriptions
    original_cancel = fake_billing.cancel_subscription
    crossed = False

    def paid_state(state):
        return replace(
            state,
            status="active",
            current_period_start=target,
            current_period_end=months_after(target, 12 if interval == "year" else 1),
            paid_current_period=settled_paid,
            latest_invoice_status="paid" if settled_paid else "open",
        )

    async def crossing_list(*, customer_id):
        nonlocal crossed
        if settles_during == "list" and not crossed:
            crossed = True
            fixed_clock.advance(timedelta(seconds=2))
            fake_billing.complete_pending_paid_signup(operation_id)
            state = (await original_list(customer_id=customer_id))[0]
            fake_billing.set_subscription(customer_id, paid_state(state))
        return await original_list(customer_id=customer_id)

    async def crossing_cancel(*, subscription_id):
        nonlocal crossed
        if settles_during == "cancel" and not crossed:
            crossed = True
            fixed_clock.advance(timedelta(seconds=2))
            state = (await original_list(customer_id="cus_fake_1"))[0]
            fake_billing.set_subscription("cus_fake_1", paid_state(state))
        await original_cancel(subscription_id=subscription_id)

    if settles_during == "cancel":
        fake_billing.complete_pending_paid_signup(operation_id)
    monkeypatch.setattr(fake_billing, "list_subscriptions", crossing_list)
    monkeypatch.setattr(fake_billing, "cancel_subscription", crossing_cancel)
    if not settled_paid:
        fake_billing.unsettled_invoice_customers.add("cus_fake_1")
    result = await authed_client.post(SIGNUPS + "/" + request["operation_id"] + "/cancel")
    assert result.json()["status"] == "refused", result.text
    assert crossed
    assert len(fake_billing.cancelled_subscriptions) == 1
    assert len(fake_billing.paid_signup_create_attempts) == 1
    me = (await authed_client.get("/api/v1/billing/me")).json()
    if settled_paid:
        paid_end = months_after(target, 12 if interval == "year" else 1)
        assert me["subscribed"] is True
        assert (
            datetime.fromisoformat(me["subscription"]["paid_through"].replace("Z", "+00:00"))
            == paid_end
        )
        usage = (await authed_client.get("/api/v1/usage")).json()["allowance"]
        assert usage["generations"]["limit"] == 500 and usage["trial"] is False
        assert datetime.fromisoformat(usage["resets_at"].replace("Z", "+00:00")) == months_after(
            target, 1
        )
        fixed_clock.advance(paid_end - fixed_clock())
        assert (await authed_client.get("/api/v1/billing/me")).json()["subscribed"] is False
    else:
        assert me["subscribed"] is False and me["subscription"] is None
        async with db_session_maker() as deletion_db:
            with pytest.raises(ConflictError):
                await delete_account(deletion_db, fake_billing, user_id=user.id)


async def test_final_settlement_read_keeps_an_already_preserved_paid_allowance(
    authed_client, coupons, fake_billing, fixed_clock, monkeypatch
):
    free, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    fake_billing.delay_paid_signup_creation = True
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "pending"
    target = datetime.fromisoformat(free["ends_at"].replace("Z", "+00:00"))
    fixed_clock.advance(target + timedelta(seconds=1) - fixed_clock())
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "pending"
    fake_billing.complete_pending_paid_signup(fake_billing.paid_signup_create_attempts[0])
    original_cancel = fake_billing.cancel_subscription

    async def change_offer_during_cancel(*, subscription_id):
        monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 300)
        await original_cancel(subscription_id=subscription_id)

    monkeypatch.setattr(fake_billing, "cancel_subscription", change_offer_during_cancel)
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "refused"
    usage = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert usage["generations"]["limit"] == 500
    assert usage["trial"] is False


async def test_webhook_cancellation_uses_fresh_clock_after_first_payment_read(
    authed_client, coupons, fake_billing, fixed_clock, monkeypatch
):
    free, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    fake_billing.delay_paid_signup_creation = True
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "pending"
    target = datetime.fromisoformat(free["ends_at"].replace("Z", "+00:00"))
    fixed_clock.advance(target - timedelta(seconds=1) - fixed_clock())
    assert (await authed_client.post(SIGNUPS + "/" + request["operation_id"] + "/cancel")).json()[
        "status"
    ] == "pending"
    original_list = fake_billing.list_subscriptions
    crossed = False

    async def crossing_list(*, customer_id):
        nonlocal crossed
        if not crossed:
            crossed = True
            fixed_clock.advance(timedelta(seconds=2))
            fake_billing.complete_pending_paid_signup(fake_billing.paid_signup_create_attempts[0])
        return await original_list(customer_id=customer_id)

    monkeypatch.setattr(fake_billing, "list_subscriptions", crossing_list)
    await _send(
        authed_client,
        fake_billing,
        "evt_cross_payment",
        "customer.subscription.created",
        {"customer": "cus_fake_1"},
    )
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "refused"
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscribed"] is True
    assert datetime.fromisoformat(
        me["subscription"]["paid_through"].replace("Z", "+00:00")
    ) == months_after(target, 1)
    assert (await authed_client.get("/api/v1/usage")).json()["allowance"]["generations"][
        "limit"
    ] == 500


async def test_cancellation_waits_for_an_attributed_final_ended_state(
    authed_client, coupons, fake_billing, monkeypatch
):
    _, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    fake_billing.delay_paid_signup_creation = True
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "pending"
    fake_billing.complete_pending_paid_signup(fake_billing.paid_signup_create_attempts[0])
    original_list = fake_billing.list_subscriptions

    async def missing_after_cancel(*, customer_id):
        return (
            []
            if fake_billing.cancelled_subscriptions
            else await original_list(customer_id=customer_id)
        )

    monkeypatch.setattr(fake_billing, "list_subscriptions", missing_after_cancel)
    result = await authed_client.post(SIGNUPS + "/" + request["operation_id"] + "/cancel")
    assert result.json()["status"] == "pending"
    assert (await authed_client.get("/api/v1/billing/me")).json()[
        "pending_paid_signup_id"
    ] == request["operation_id"]
    monkeypatch.setattr(fake_billing, "list_subscriptions", original_list)
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "refused"


async def test_replay_deadline_is_rechecked_after_provider_waits_before_dispatch(
    authed_client, coupons, fake_billing, fixed_clock, monkeypatch, db_session_maker, user
):
    _, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    fake_billing.delay_paid_signup_creation = True
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "pending"
    fixed_clock.advance(timedelta(hours=23) - timedelta(seconds=1))
    original_list = fake_billing.list_subscriptions
    reads = 0

    async def wait_during_dispatch_read(*, customer_id):
        nonlocal reads
        reads += 1
        if reads == 2:
            fixed_clock.advance(timedelta(hours=2))
        return await original_list(customer_id=customer_id)

    monkeypatch.setattr(fake_billing, "list_subscriptions", wait_during_dispatch_read)
    result = await authed_client.get(SIGNUPS + "/" + request["operation_id"])
    assert reads >= 2
    assert result.json()["status"] == "pending"
    assert len(fake_billing.paid_signup_create_attempts) == 1
    assert (await authed_client.get("/api/v1/billing/me")).json()[
        "pending_paid_signup_id"
    ] == request["operation_id"]
    async with db_session_maker() as deletion_db:
        with pytest.raises(ConflictError):
            await delete_account(deletion_db, fake_billing, user_id=user.id)


@pytest.mark.parametrize("after_original_target", [False, True])
async def test_stale_signup_cancellation_after_coupon_extension_requires_current_plan_action(
    authed_client, coupons, fake_billing, fixed_clock, after_original_target
):
    free, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    await _send(
        authed_client,
        fake_billing,
        "evt_other_browser_complete",
        "checkout.session.completed",
        {"customer": "cus_fake_1"},
    )
    second = await coupons("--months", "2")
    offer = (await authed_client.post(PREVIEW, json={"code": second["code"]})).json()
    assert (
        await authed_client.post(
            REDEEM, json=confirmation(offer, operation="other-browser-extension-0001")
        )
    ).json()["status"] == "completed"
    if after_original_target:
        target = datetime.fromisoformat(free["ends_at"].replace("Z", "+00:00"))
        fixed_clock.advance(target + timedelta(seconds=1) - fixed_clock())
    before = (await authed_client.get("/api/v1/usage")).json()
    stale = await authed_client.post(SIGNUPS + "/" + request["operation_id"] + "/cancel")
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "PAID_SIGNUP_CANCEL_CONFLICT"
    assert "Cancellation could not be confirmed" in stale.json()["detail"]
    assert "Settings" in stale.json()["detail"] and "Cancel renewal" in stale.json()["detail"]
    assert fake_billing.cancelled_subscriptions == []
    assert (await authed_client.get("/api/v1/usage")).json() == before
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["free_access"]["ends_at"] == offer["ends_at"]
    assert me["subscription"]["current_period_end"] == offer["ends_at"]
    cancelled = await authed_client.post("/api/v1/billing/cancel-renewal")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["subscription"]["cancel_at"] == offer["ends_at"]
    assert cancelled.json()["free_access"]["ends_at"] == offer["ends_at"]


async def test_stale_completed_signup_cancellation_after_paid_start_is_explicit_conflict(
    authed_client, coupons, fake_billing, fixed_clock
):
    free, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "completed"
    target = datetime.fromisoformat(free["ends_at"].replace("Z", "+00:00"))
    fixed_clock.advance(target + timedelta(seconds=1) - fixed_clock())
    state = (await fake_billing.list_subscriptions(customer_id="cus_fake_1"))[0]
    fake_billing.set_subscription(
        "cus_fake_1",
        replace(
            state,
            status="active",
            current_period_start=target,
            current_period_end=months_after(target, 1),
            paid_current_period=True,
        ),
    )
    await _send(
        authed_client,
        fake_billing,
        "evt_paid_start",
        "customer.subscription.updated",
        {"customer": "cus_fake_1"},
    )
    before = (await authed_client.get("/api/v1/usage")).json()
    result = await authed_client.post(SIGNUPS + "/" + request["operation_id"] + "/cancel")
    assert result.status_code == 409, result.text
    assert "Manage subscription" in result.json()["detail"]
    assert fake_billing.cancelled_subscriptions == []
    assert (await authed_client.get("/api/v1/usage")).json() == before


@pytest.mark.parametrize("mismatch", ["price", "provider-error"])
async def test_completed_signup_cancellation_does_not_claim_success_for_unknown_provider_facts(
    authed_client, coupons, fake_billing, mismatch
):
    _, request, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "completed"
    if mismatch == "price":
        state = (await fake_billing.list_subscriptions(customer_id="cus_fake_1"))[0]
        fake_billing.set_subscription("cus_fake_1", replace(state, price_id="price_unknown"))
    else:
        fake_billing.fail_on.add("list_subscriptions")
    result = await authed_client.post(SIGNUPS + "/" + request["operation_id"] + "/cancel")
    assert result.status_code == 409, result.text
    assert result.json()["code"] == "PAID_SIGNUP_CANCEL_CONFLICT"
    assert fake_billing.cancelled_subscriptions == []
