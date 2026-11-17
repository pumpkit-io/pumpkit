import asyncio
import hashlib
import json
import threading
from dataclasses import replace
from datetime import datetime, timedelta
from io import StringIO
from types import SimpleNamespace
from typing import Any, cast

import pytest
import stripe
from sqlalchemy import delete, event, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from pumpkit.account_deletion import run_cli as delete_cli
from pumpkit.billing.checkout_drain import run_cli
from pumpkit.billing.gateway import (
    BillingProviderError,
    CheckoutOutcomeUnknown,
    HostedCheckout,
    StripeBillingGateway,
    SubscriptionState,
    TopUpPurchase,
)
from pumpkit.billing.models import CheckoutDispatch, CheckoutFence, PaidSignup
from pumpkit.billing.paid_signup_recovery import run_cli as recover_signups
from pumpkit.core.config import settings
from tests.billing.checkout_drain import drain, review
from tests.billing.paid_signups import SIGNUPS, accept_paid_signup, open_paid_signup, redeem_coupon
from tests.billing.test_billing import CHECKOUT, CHECKOUT_MONTHLY, MONTHLY
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_monthly_coupons import monthly
from tests.billing.test_top_ups import ACCEPTANCE, TOP_UP_CHECKOUT, _send
from tests.billing.test_top_ups import sells_top_ups as sells_top_ups


async def test_drain_preview_does_not_claim_empty_inventory_proves_legacy_dispatch_finished(
    db_session_maker, fake_billing, monkeypatch
):
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    out = StringIO()
    assert (
        await run_cli(["preview"], sessions=db_session_maker, gateway=fake_billing, stdout=out) == 1
    )
    report = json.loads(out.getvalue())
    assert report["ready"] is False
    assert "legacy_evidence_required" in report["blockers"]
    assert report["fence"]["closed"] is False
    assert report["proposed_expirations"] == []


async def test_lost_checkout_response_blocks_replacement_and_both_account_deletion_paths(
    client, fake_billing, db_session_maker, file_storage, user
):

    fake_billing.plans = [MONTHLY]
    fake_billing.fail_on.add("after_dispatch_checkout")
    assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 502
    fake_billing.fail_on.clear()
    response = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)
    assert response.status_code == 409
    assert len(fake_billing.checkouts) == 1
    response = await client.request("DELETE", "/api/v1/users/me", json={"handle": "ada"})
    assert response.status_code == 409
    out, error = StringIO(), StringIO()
    assert (
        await delete_cli(
            ["--user-id", user.id],
            sessions=db_session_maker,
            gateway=fake_billing,
            storage=file_storage,
            stdout=out,
            stderr=error,
        )
        == 1
    )
    assert "checkout is being confirmed" in error.getvalue()
    assert fake_billing.cancelled_subscriptions == []
    assert (await client.get("/api/v1/users/me")).status_code == 200


async def test_execute_requires_bound_reviewed_evidence_and_expires_owned_checkout_once(
    client, fake_billing, db_session_maker, monkeypatch, tmp_path
):

    fake_billing.plans = [MONTHLY]
    assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 200
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    out = StringIO()
    assert (
        await run_cli(["execute"], sessions=db_session_maker, gateway=fake_billing, stdout=out) == 1
    )
    first = json.loads(out.getvalue())
    assert first["fence"]["closed"] is True
    assert fake_billing.expired_hosted_checkouts == []
    evidence = {
        "schema_version": 1,
        "binding": first["binding"],
        "pause": {
            "release": "release-reviewed",
            "image": "sha256:reviewed-image",
            "operation": "pause-reviewed",
            "creator_evidence": {
                creator: "protected-review-reference"
                for creator in ["backend", "publisher", "coupon-maintenance", "recovery-cli"]
            },
        },
        "legacy": {
            "completeness_evidence": "reviewed-request-population",
            "no_applicable_dispatch_evidence": "reviewed-no-legacy-dispatches",
            "requests": [],
        },
        "review": {"operator": "operator", "reviewer": "reviewer", "record": "activation-review"},
    }
    path = tmp_path / "evidence.json"
    content = json.dumps(evidence).encode()
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    args = ["execute", "--evidence", str(path), "--reviewed-evidence-sha256", digest]
    out = StringIO()
    assert await run_cli(args, sessions=db_session_maker, gateway=fake_billing, stdout=out) == 0
    ready = json.loads(out.getvalue())
    assert ready["ready"] is True
    assert ready["receipt"]
    assert fake_billing.expired_hosted_checkouts == ["cs_fake_1"]
    assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 503
    out = StringIO()
    assert await run_cli(args, sessions=db_session_maker, gateway=fake_billing, stdout=out) == 0
    assert fake_billing.expired_hosted_checkouts == ["cs_fake_1"]
    monkeypatch.setattr(settings, "BILLING_TRIAL_PERIOD_DAYS", 8)
    out = StringIO()
    assert await run_cli(args, sessions=db_session_maker, gateway=fake_billing, stdout=out) == 1
    assert "configuration_changed" in json.loads(out.getvalue())["blockers"]


async def test_cancelled_http_request_waits_for_actual_sync_sdk_worker_before_releasing_dispatch(
    client, fake_billing, monkeypatch
):

    entered, finish, exited = threading.Event(), threading.Event(), threading.Event()

    def create(params, options):
        entered.set()
        assert finish.wait(5)
        exited.set()
        return SimpleNamespace(id="cs_threaded", url="https://checkout.test/threaded")

    sdk = SimpleNamespace(
        v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create=create)))
    )
    adapter = StripeBillingGateway(client=cast(Any, sdk))
    monkeypatch.setattr(fake_billing, "dispatch_checkout", adapter.dispatch_checkout)
    fake_billing.plans = [MONTHLY]
    request = asyncio.create_task(client.post(CHECKOUT, json=CHECKOUT_MONTHLY))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        request.cancel()
        await asyncio.sleep(0.05)
        assert not request.done()
        assert not exited.is_set()
    finally:
        finish.set()
        await asyncio.gather(request, return_exceptions=True)
    assert exited.is_set()


@pytest.mark.parametrize("kind", ["subscription", "top_up", "arranged_paid_signup"])
@pytest.mark.parametrize("lost_response", [False, True])
async def test_all_purchase_paths_drain_without_losing_free_access_or_duplicate_benefits(
    authed_client,
    coupons,
    fake_billing,
    fixed_clock,
    db_session_maker,
    monkeypatch,
    tmp_path,
    sells_top_ups,
    kind,
    lost_response,
):
    fake_billing.clock = fixed_clock
    free = None
    if kind != "subscription":
        free = await redeem_coupon(authed_client, coupons)
    if lost_response:
        fake_billing.fail_on.add("after_dispatch_checkout")
    request = {}
    if kind == "arranged_paid_signup":
        request, response = await accept_paid_signup(authed_client)
        assert response["status"] == "pending"
    else:
        path = CHECKOUT if kind == "subscription" else TOP_UP_CHECKOUT
        payload = CHECKOUT_MONTHLY if kind == "subscription" else ACCEPTANCE
        response = await authed_client.post(path, json=payload)
        assert response.status_code == (502 if lost_response else 200)
    fake_billing.fail_on.clear()
    before = (await authed_client.get("/api/v1/usage")).json()
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    evidence = review(tmp_path / "review.json", closed["binding"])
    code, ready = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 0, ready
    assert ready["ready"] is True
    assert len(fake_billing.expired_hosted_checkouts) == 1
    assert len(fake_billing.checkout_dispatches) == 1
    assert (await authed_client.get("/api/v1/usage")).json() == before
    if free:
        me = (await authed_client.get("/api/v1/billing/me")).json()
        assert me["free_access"]["ends_at"] == free["ends_at"]
    if kind == "arranged_paid_signup":
        assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
            "status"
        ] == "refused"
    code, again = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 0, again
    assert len(fake_billing.expired_hosted_checkouts) == 1


@pytest.mark.parametrize(
    "contradiction", ["foreign", "unattached", "user", "kind", "seller", "origin"]
)
async def test_drain_leaves_foreign_unknown_and_contradictory_sessions_untouched(
    client, fake_billing, fixed_clock, db_session_maker, monkeypatch, tmp_path, contradiction
):
    fake_billing.plans = [MONTHLY]
    assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 200
    session = fake_billing.hosted_checkouts["cs_fake_1"]
    candidate = replace(session, id="cs_candidate")
    if contradiction == "foreign":
        candidate = replace(
            candidate,
            customer_id="cus_foreign",
            user_id="other-app-user",
            metadata={},
            success_url="https://other-app.test/success",
            cancel_url="https://other-app.test/cancel",
        )
    elif contradiction == "unattached":
        candidate = replace(
            candidate, customer_id="cus_unattached", user_id="missing-user", metadata={}
        )
    elif contradiction == "user":
        candidate = replace(candidate, user_id="contradictory-user")
    elif contradiction == "kind":
        candidate = replace(candidate, metadata={**candidate.metadata, "pumpkit_kind": "top_up"})
    elif contradiction == "seller":
        candidate = replace(candidate, managed_payments=True)
    else:
        candidate = replace(candidate, cancel_url="https://other-app.test/cancel")
    fake_billing.hosted_checkouts[candidate.id] = candidate
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    evidence = review(tmp_path / "review.json", closed["binding"])
    code, result = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == (0 if contradiction == "foreign" else 1), result
    assert fake_billing.expired_hosted_checkouts == ["cs_fake_1"]
    assert (await fake_billing.read_checkout(session_id="cs_candidate")).status == "open"
    if contradiction != "foreign":
        assert "cs_candidate" in result["unknown"]


@pytest.mark.parametrize("kind", ["top_up", "arranged_paid_signup"])
async def test_expiration_racing_payment_reconciles_current_state_and_never_duplicates_benefits(
    authed_client,
    coupons,
    fake_billing,
    fixed_clock,
    db_session_maker,
    monkeypatch,
    tmp_path,
    sells_top_ups,
    kind,
):
    fake_billing.clock = fixed_clock
    free = await redeem_coupon(authed_client, coupons)
    request = {}
    if kind == "top_up":
        opened = (await authed_client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)).json()
    else:
        request, opened = await accept_paid_signup(authed_client)
    session_id = opened["session_id"]

    async def payment_wins(*, session_id):
        if kind == "top_up":
            fake_billing.set_top_up(
                "cus_fake_1",
                TopUpPurchase(
                    checkout_session_id=session_id, paid_at=fixed_clock(), reversed=False
                ),
            )
        else:
            fake_billing.complete_paid_signup_checkout(session_id)
        raise BillingProviderError("Payment completed before expiration")

    monkeypatch.setattr(fake_billing, "expire_checkout", payment_wins)
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    evidence = review(tmp_path / "review.json", closed["binding"])
    code, result = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 0, result
    assert result["completed"] == [session_id]
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["free_access"]["ends_at"] == free["ends_at"]
    usage = (await authed_client.get("/api/v1/usage")).json()
    if kind == "top_up":
        assert usage["allowance"]["top_ups"]
    else:
        signup = (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()
        assert signup["status"] == "completed"
        assert signup["first_payment_at"] == free["ends_at"]
    code, again = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 0, again
    assert (await authed_client.get("/api/v1/usage")).json() == usage


@pytest.mark.parametrize("state", ["unpaid", "processing", "unknown"])
async def test_current_unsettled_or_unreadable_checkout_cannot_issue_readiness(
    client, fake_billing, fixed_clock, db_session_maker, monkeypatch, tmp_path, state
):
    fake_billing.plans = [MONTHLY]
    assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 200
    current = fake_billing.hosted_checkouts["cs_fake_1"]
    fake_billing.hosted_checkouts[current.id] = replace(
        current, status="complete", payment_status=state
    )
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    evidence = review(tmp_path / "review.json", closed["binding"])
    code, result = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 1
    assert result["ready"] is False
    assert current.id in result["unknown"]


async def test_provider_incident_does_not_become_resolved_from_one_empty_listing_or_replay(
    client, fake_billing, fixed_clock, db_session_maker, monkeypatch, tmp_path
):
    async def incident(**kwargs):
        raise CheckoutOutcomeUnknown("Provider 500 may still produce an object")

    monkeypatch.setattr(fake_billing, "dispatch_checkout", incident)
    fake_billing.plans = [MONTHLY]
    assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 502
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    evidence = review(tmp_path / "review.json", closed["binding"])
    for _ in range(2):
        code, result = await drain(
            db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
        )
        assert code == 1
        assert "dispatch_unresolved" in result["blockers"]
        assert result["unresolved_dispatches"]


@pytest.mark.parametrize("kind", ["subscription", "top_up"])
async def test_completed_checkout_waits_for_actual_subscription_or_top_up_visibility(
    authed_client,
    coupons,
    fake_billing,
    fixed_clock,
    db_session_maker,
    monkeypatch,
    tmp_path,
    sells_top_ups,
    kind,
):
    fake_billing.clock = fixed_clock
    if kind == "top_up":
        await redeem_coupon(authed_client, coupons)
    path = CHECKOUT if kind == "subscription" else TOP_UP_CHECKOUT
    payload = CHECKOUT_MONTHLY if kind == "subscription" else ACCEPTANCE
    opened = (await authed_client.post(path, json=payload)).json()
    session_id = opened["session_id"]
    current = fake_billing.hosted_checkouts[session_id]
    fake_billing.hosted_checkouts[session_id] = replace(
        current,
        status="complete",
        payment_status="paid",
        subscription_id="sub_late" if kind == "subscription" else None,
    )
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    evidence = review(tmp_path / "review.json", closed["binding"])
    code, pending = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 1
    assert "completed_purchase_unconfirmed" in pending["blockers"]
    assert pending["completed"] == []
    if kind == "top_up":
        fake_billing.set_top_up(
            "cus_fake_1",
            TopUpPurchase(checkout_session_id=session_id, paid_at=fixed_clock(), reversed=False),
        )
    else:
        fake_billing.set_subscription(
            "cus_fake_1",
            SubscriptionState(
                id="sub_late",
                status="active",
                price_id="price_monthly",
                plan_key="pumpkit_pro_monthly",
                created_at=fixed_clock(),
                current_period_end=fixed_clock() + timedelta(days=30),
                billing_cycle_anchor=fixed_clock(),
                current_period_start=fixed_clock(),
                paid_current_period=True,
                latest_invoice_status="paid",
                interval="month",
                interval_count=1,
            ),
        )
    code, confirmed = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 0, confirmed
    assert confirmed["completed"] == [session_id]
    before = (await authed_client.get("/api/v1/usage")).json()
    code, _ = await drain(db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock)
    assert code == 0
    assert (await authed_client.get("/api/v1/usage")).json() == before
    assert (await authed_client.get("/api/v1/billing/me")).json()["subscribed"] is True


async def test_original_idempotency_window_expiry_never_authorizes_a_fresh_key(
    client, fake_billing, fixed_clock, db_session_maker, monkeypatch, tmp_path
):
    fake_billing.plans = [MONTHLY]
    fake_billing.fail_on.add("create_subscription_checkout")
    assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 502
    fake_billing.fail_on.clear()
    fixed_clock.advance(timedelta(hours=24))
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    evidence = review(tmp_path / "review.json", closed["binding"])
    code, result = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 1
    assert "dispatch_unresolved" in result["blockers"]
    assert fake_billing.checkouts == []
    assert len(fake_billing.checkout_dispatches) == 1


@pytest.mark.parametrize("selected", [False, True])
async def test_drain_refuses_incomplete_pause_or_selected_verification_identity(
    fake_billing, fixed_clock, db_session_maker, monkeypatch, user, selected
):
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", selected)
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", user.id if selected else None)
    code, result = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    assert code == 1
    assert "complete_pause_required" in result["blockers"]
    assert result["fence"]["closed"] is False
    assert fake_billing.expired_hosted_checkouts == []


async def test_interrupted_checkpoint_requires_specific_reviewed_worker_and_request_resolution(
    client, fake_billing, fixed_clock, db_session_maker, monkeypatch, tmp_path
):
    fake_billing.plans = [MONTHLY]
    failed = False

    def fail_result_checkpoint(db):
        nonlocal failed
        if not failed and any(
            isinstance(row, CheckoutDispatch) and row.session_id for row in db.identity_map.values()
        ):
            failed = True
            raise RuntimeError("Controlled checkpoint interruption after provider returned")

    event.listen(Session, "before_commit", fail_result_checkpoint)
    try:
        assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 500
    finally:
        event.remove(Session, "before_commit", fail_result_checkpoint)
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    evidence = review(tmp_path / "review.json", closed["binding"])
    code, unknown = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 1
    assert "dispatch_unresolved" in unknown["blockers"]
    key, params = next(iter(fake_billing.checkout_dispatches.items()))
    resolution = {
        "dispatch_id": params["metadata"]["pumpkit_dispatch"],
        "parameters_sha256": hashlib.sha256(
            json.dumps(params, sort_keys=True).encode()
        ).hexdigest(),
        "idempotency_key_sha256": hashlib.sha256(key.encode()).hexdigest(),
        "worker_resolution_evidence": "controlled-provider-worker-returned-before-failed-checkpoint",
        "provider_resolution_evidence": "controlled-exact-original-request-object",
        "outcome": "object",
        "session_id": "cs_fake_1",
    }
    evidence = review(tmp_path / "review.json", closed["binding"], resolutions=[resolution])
    code, resolved = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 0, resolved
    assert fake_billing.expired_hosted_checkouts == ["cs_fake_1"]
    assert len(fake_billing.checkouts) == 1


async def test_unknown_top_up_does_not_block_subscription_cancellation_or_management_during_pause(
    client, fake_billing, fixed_clock, db, user, monkeypatch, sells_top_ups, coupons
):
    await monthly(db, user, fake_billing, fixed_clock)
    assert (
        await _send(
            client,
            fake_billing,
            "evt_paid",
            "customer.subscription.updated",
            {"customer": "cus_monthly"},
        )
    ).status_code == 200
    fake_billing.fail_on.add("after_dispatch_checkout")
    assert (await client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)).status_code == 502
    fake_billing.fail_on.clear()
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    cancelled = await client.post("/api/v1/billing/cancel-renewal")
    assert cancelled.status_code == 200, cancelled.text
    portal = await client.post("/api/v1/billing/portal")
    assert portal.status_code == 200, portal.text


async def test_changed_configuration_can_start_a_fresh_closed_generation_without_clearing_intents(
    client, fake_billing, fixed_clock, db_session_maker, monkeypatch, tmp_path
):
    fake_billing.plans = [MONTHLY]
    fake_billing.fail_on.add("after_dispatch_checkout")
    assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 502
    fake_billing.fail_on.clear()
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    old_evidence = review(tmp_path / "old-review.json", closed["binding"])
    monkeypatch.setattr(settings, "BILLING_TRIAL_PERIOD_DAYS", 8)
    _, stale = await drain(
        db_session_maker, fake_billing, ["status", *old_evidence], clock=fixed_clock
    )
    assert "configuration_changed" in stale["blockers"]
    recapture = [
        "execute",
        "--recapture-generation",
        str(closed["fence"]["generation"]),
        "--current-fingerprint",
        stale["current_config_fingerprint"],
    ]
    code, fresh = await drain(db_session_maker, fake_billing, recapture, clock=fixed_clock)
    assert code == 1
    assert fresh["fence"]["closed"] is True
    assert fresh["fence"]["generation"] == closed["fence"]["generation"] + 1
    assert "legacy_evidence_required" in fresh["blockers"]
    assert fresh["unresolved_dispatches"]
    assert fake_billing.expired_hosted_checkouts == []
    assert len(fake_billing.checkouts) == 1
    code, refused = await drain(db_session_maker, fake_billing, recapture, clock=fixed_clock)
    assert code == 1
    assert "recapture_binding_invalid" in refused["blockers"]
    code, refused = await drain(
        db_session_maker, fake_billing, ["execute", *old_evidence], clock=fixed_clock
    )
    assert code == 1
    assert "evidence_binding_mismatch" in refused["blockers"]
    evidence = review(tmp_path / "fresh-review.json", fresh["binding"])
    code, ready = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 0, ready
    assert fake_billing.expired_hosted_checkouts == ["cs_fake_1"]
    assert next(iter(fake_billing.checkout_dispatches.values()))["subscription_data"] == {
        "trial_period_days": 7
    }


async def test_pre_cutover_abort_releases_only_fence_while_full_pause_stays_authoritative(
    client, fake_billing, fixed_clock, db_session_maker, monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    evidence = review(tmp_path / "review.json", closed["binding"])
    code, ready = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 0, ready
    args = [
        "release",
        *evidence,
        "--generation",
        str(ready["fence"]["generation"]),
        "--receipt",
        ready["receipt"],
        "--target-fingerprint",
        ready["current_config_fingerprint"],
    ]
    code, released = await drain(db_session_maker, fake_billing, args, clock=fixed_clock)
    assert code == 0, released
    assert released["fence"]["closed"] is False
    assert settings.BILLING_PURCHASES_PAUSED is True
    assert settings.STRIPE_MANAGED_PAYMENTS is False
    assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 503
    code, replayed = await drain(db_session_maker, fake_billing, args, clock=fixed_clock)
    assert code == 0 and replayed["release_replayed"] is True
    assert replayed["fence"] == released["fence"]
    _, recaptured = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    code, stale = await drain(db_session_maker, fake_billing, args, clock=fixed_clock)
    assert code == 1
    assert "release_binding_invalid" in stale["blockers"]
    assert stale["fence"] == recaptured["fence"]


async def test_drain_rechecks_current_ownership_before_expiration_mutation(
    client, fake_billing, fixed_clock, db_session_maker, monkeypatch, tmp_path
):
    fake_billing.plans = [MONTHLY]
    assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 200
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    evidence = review(tmp_path / "review.json", closed["binding"])
    original = fake_billing.read_checkout
    calls = 0

    async def changed_after_inventory(*, session_id):
        nonlocal calls
        calls += 1
        state = await original(session_id=session_id)
        if calls >= 3:
            return replace(state, user_id="contradictory-current-owner")
        return state

    monkeypatch.setattr(fake_billing, "read_checkout", changed_after_inventory)
    code, result = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 1
    assert result["ready"] is False
    assert fake_billing.expired_hosted_checkouts == []
    assert "cs_fake_1" in result["unknown"]


@pytest.mark.parametrize("operation", ["receipt", "release"])
@pytest.mark.parametrize("checkpoint", ["before_commit", "after_commit"])
async def test_operator_checkpoint_failure_never_reports_unverified_success_and_retry_reconciles(
    client,
    fake_billing,
    fixed_clock,
    db_session_maker,
    monkeypatch,
    tmp_path,
    operation,
    checkpoint,
):
    fake_billing.plans = [MONTHLY]
    assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 200
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    evidence = review(tmp_path / "review.json", closed["binding"])
    args = ["execute", *evidence]
    prior = None
    if operation == "release":
        code, prior = await drain(db_session_maker, fake_billing, args, clock=fixed_clock)
        assert code == 0, prior
        args = [
            "release",
            *evidence,
            "--generation",
            str(prior["fence"]["generation"]),
            "--receipt",
            prior["receipt"],
            "--target-fingerprint",
            prior["current_config_fingerprint"],
        ]

    def fail_checkpoint(db):
        for row in db.identity_map.values():
            if isinstance(row, CheckoutFence) and (
                (operation == "receipt" and row.receipt)
                or (operation == "release" and not row.closed)
            ):
                raise SQLAlchemyError("Controlled operator checkpoint acknowledgement loss")

    event.listen(Session, checkpoint, fail_checkpoint)
    try:
        code, failed = await drain(db_session_maker, fake_billing, args, clock=fixed_clock)
    finally:
        event.remove(Session, checkpoint, fail_checkpoint)
    assert code == 1
    assert failed["ready"] is False
    assert failed.get("released") is not True
    assert failed["receipt"] is None
    assert "provider_or_coordination_unavailable" in failed["blockers"]
    code, resumed = await drain(db_session_maker, fake_billing, args, clock=fixed_clock)
    assert code == 0, resumed
    assert fake_billing.expired_hosted_checkouts == ["cs_fake_1"]
    if operation == "receipt":
        assert resumed["ready"] is True
        code, status = await drain(
            db_session_maker, fake_billing, ["status", *evidence], clock=fixed_clock
        )
        assert code == 0 and status["receipt"] == resumed["receipt"]
    else:
        assert prior is not None
        assert resumed["released"] is True
        assert resumed["fence"]["generation"] == prior["fence"]["generation"] + 1
        assert resumed["fence"]["closed"] is False
        code, again = await drain(db_session_maker, fake_billing, args, clock=fixed_clock)
        assert code == 0 and again["fence"] == resumed["fence"]


async def test_surviving_local_user_reference_keeps_detached_historical_origin_unverified(
    client, user, fake_billing, fixed_clock, db_session_maker, monkeypatch, tmp_path
):
    fake_billing.plans = [MONTHLY]
    assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 200
    original = fake_billing.hosted_checkouts["cs_fake_1"]
    fake_billing.hosted_checkouts["cs_old_orphan"] = replace(
        original,
        id="cs_old_orphan",
        customer_id="cus_detached",
        metadata={},
        success_url="https://historical-origin.test/billing/success",
        cancel_url="https://historical-origin.test/billing/cancelled",
    )
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    evidence = review(tmp_path / "review.json", closed["binding"])
    code, result = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 1
    assert "cs_old_orphan" in result["unknown"]
    assert fake_billing.expired_hosted_checkouts == ["cs_fake_1"]
    assert (await fake_billing.read_checkout(session_id="cs_old_orphan")).status == "open"


async def test_reviewed_legacy_object_uses_local_customer_user_and_original_route_relationships(
    client, fake_billing, fixed_clock, db_session_maker, monkeypatch, tmp_path
):
    fake_billing.plans = [MONTHLY]
    assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 200
    original = fake_billing.hosted_checkouts["cs_fake_1"]
    fake_billing.hosted_checkouts["cs_legacy_owned"] = replace(
        original, id="cs_legacy_owned", metadata={}
    )
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    original_parameters = {**next(iter(fake_billing.checkout_dispatches.values())), "metadata": {}}
    parameters_digest = hashlib.sha256(
        json.dumps(original_parameters, sort_keys=True).encode()
    ).hexdigest()
    requests = [
        {
            "request_reference": "controlled-original-legacy-CREATE",
            "creator": "backend",
            "parameters_sha256": parameters_digest,
            "relationship_evidence": "controlled-same-local-customer-and-immutable-user-and-routes",
            "outcome_evidence": "controlled-original-response-session",
            "outcome": "object",
            "session_id": "cs_legacy_owned",
        }
    ]
    evidence = review(tmp_path / "review.json", closed["binding"], requests=requests)
    code, result = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 0, result
    assert sorted(fake_billing.expired_hosted_checkouts) == ["cs_fake_1", "cs_legacy_owned"]


@pytest.mark.parametrize(
    ("success_path", "cancel_path", "owned"),
    [
        ("/billing", "/billing", True),
        ("/billing/cancelled", "/billing/cancelled", False),
        ("/billing/success", "/billing", False),
        ("/billing", "/billing/cancelled", False),
    ],
)
async def test_retained_legacy_paid_signup_requires_historical_routes_and_preserves_offer(
    authed_client,
    coupons,
    fake_billing,
    fixed_clock,
    db_session_maker,
    monkeypatch,
    db,
    tmp_path,
    success_path,
    cancel_path,
    owned,
):
    fake_billing.clock = fixed_clock
    free, request, opened = await open_paid_signup(authed_client, coupons)
    operation = await db.scalar(
        select(PaidSignup).where(PaidSignup.operation_id == request["operation_id"])
    )
    await db.execute(delete(CheckoutDispatch).where(CheckoutDispatch.id == operation.id))
    operation.checkout_contract = 0
    await db.commit()
    session_id = opened["session_id"]
    fake_billing.hosted_checkouts[session_id] = replace(
        fake_billing.hosted_checkouts[session_id],
        success_url=f"{settings.PUBLIC_URL}{success_path}",
        cancel_url=f"{settings.PUBLIC_URL}{cancel_path}",
        metadata={"pumpkit_paid_signup": operation.id},
    )
    before = (await authed_client.get("/api/v1/usage")).json()
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    evidence = review(tmp_path / "review.json", closed["binding"])
    code, result = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == (0 if owned else 1), result
    assert result["ready"] is owned
    assert fake_billing.expired_hosted_checkouts == ([session_id] if owned else [])
    assert (await fake_billing.read_checkout(session_id=session_id)).status == (
        "expired" if owned else "open"
    )
    if not owned:
        assert session_id in result["unknown"]
    current = (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()
    assert current["status"] == ("refused" if owned else "pending")
    assert current["first_payment_at"] == free["ends_at"]
    assert (await authed_client.get("/api/v1/billing/me")).json()["free_access"]["ends_at"] == free[
        "ends_at"
    ]
    assert (await authed_client.get("/api/v1/usage")).json() == before


@pytest.mark.parametrize(
    "entry", ["status", "cancel", "elapsed", "webhook", "recovery", "deletion"]
)
async def test_absent_legacy_paid_signup_never_mints_current_replay_parameters_or_guesses_no_object(
    authed_client,
    coupons,
    fake_billing,
    fixed_clock,
    db_session_maker,
    monkeypatch,
    db,
    user,
    file_storage,
    entry,
):
    fake_billing.clock = fixed_clock
    fake_billing.fail_on.add("create_paid_signup_checkout")
    free, request, _ = await open_paid_signup(authed_client, coupons)
    operation = await db.scalar(
        select(PaidSignup).where(PaidSignup.operation_id == request["operation_id"])
    )
    await db.execute(delete(CheckoutDispatch).where(CheckoutDispatch.id == operation.id))
    operation.checkout_contract = 0
    await db.commit()
    fake_billing.fail_on.clear()
    before = len(fake_billing.checkout_dispatches)
    monkeypatch.setattr(settings, "STRIPE_MANAGED_PAYMENTS", True)
    if entry == "elapsed":
        fixed_clock.advance(timedelta(hours=25))
    if entry == "deletion":
        deleted = await authed_client.request("DELETE", "/api/v1/users/me", json={"handle": "ada"})
        assert deleted.status_code == 409
        out, error = StringIO(), StringIO()
        assert (
            await delete_cli(
                ["--user-id", user.id],
                sessions=db_session_maker,
                gateway=fake_billing,
                storage=file_storage,
                stdout=out,
                stderr=error,
            )
            == 1
        )
        assert (await authed_client.get("/api/v1/users/me")).status_code == 200
    elif entry == "recovery":
        assert (
            await recover_signups(
                ["recover"],
                sessions=db_session_maker,
                gateway=fake_billing,
                clock=fixed_clock,
                stdout=StringIO(),
            )
            == 1
        )
    elif entry == "webhook":
        assert (
            await _send(
                authed_client,
                fake_billing,
                "evt_legacy",
                "customer.subscription.updated",
                {"customer": "cus_fake_1"},
            )
        ).status_code == 200
    else:
        result = (
            await authed_client.post(SIGNUPS + "/" + request["operation_id"] + "/cancel")
            if entry == "cancel"
            else await authed_client.get(SIGNUPS + "/" + request["operation_id"])
        )
        assert result.status_code == 200
        assert result.json()["status"] == "pending"
        assert result.json()["first_payment_at"] == free["ends_at"]
    assert len(fake_billing.checkout_dispatches) == before
    assert fake_billing.paid_signup_checkouts == {}
    assert (await authed_client.get("/api/v1/billing/me")).json()["free_access"]["ends_at"] == free[
        "ends_at"
    ]


@pytest.mark.parametrize("offer_matches", [True, False])
async def test_specific_reviewed_legacy_no_object_resolution_preserves_offer_and_never_replays_old_key(
    authed_client,
    coupons,
    fake_billing,
    fixed_clock,
    db_session_maker,
    monkeypatch,
    db,
    tmp_path,
    offer_matches,
):
    fake_billing.clock = fixed_clock
    fake_billing.fail_on.add("create_paid_signup_checkout")
    free, request, _ = await open_paid_signup(authed_client, coupons)
    operation = await db.scalar(
        select(PaidSignup).where(PaidSignup.operation_id == request["operation_id"])
    )
    key, recorded = next(iter(fake_billing.checkout_dispatches.items()))
    parameters = {**recorded, "metadata": {"pumpkit_paid_signup": operation.id}}
    await db.execute(delete(CheckoutDispatch).where(CheckoutDispatch.id == operation.id))
    operation.checkout_contract = 0
    await db.commit()
    fake_billing.fail_on.clear()
    fixed_clock.advance(timedelta(hours=25))
    monkeypatch.setattr(settings, "STRIPE_MANAGED_PAYMENTS", True)
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://new-origin.test")
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    offer_digest = hashlib.sha256(json.dumps(operation.offer, sort_keys=True).encode()).hexdigest()
    proof = {
        "request_reference": "controlled-original-legacy-create-and-key",
        "creator": "backend",
        "parameters_sha256": hashlib.sha256(
            json.dumps(parameters, sort_keys=True).encode()
        ).hexdigest(),
        "relationship_evidence": "controlled-original-customer-user-accepted-operation",
        "outcome_evidence": "controlled-worker-finished-and-specific-provider-no-object-resolution",
        "outcome": "provider_resolved_no_object",
        "paid_signup_id": operation.id,
        "accepted_offer_sha256": offer_digest if offer_matches else "0" * 64,
        "idempotency_key_sha256": hashlib.sha256(key.encode()).hexdigest(),
        "parameters": parameters,
    }
    evidence = review(tmp_path / "review.json", closed["binding"], requests=[proof])
    code, result = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == (0 if offer_matches else 1), result
    current = (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()
    assert current["status"] == ("refused" if offer_matches else "pending")
    assert current["first_payment_at"] == free["ends_at"]
    assert (await authed_client.get("/api/v1/billing/me")).json()["free_access"]["ends_at"] == free[
        "ends_at"
    ]
    assert fake_billing.paid_signup_checkouts == {}
    assert len(fake_billing.checkout_dispatches) == 1
    if offer_matches:
        code, resumed = await drain(
            db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
        )
        assert code == 0 and resumed["receipt"] == result["receipt"]
        assert fake_billing.paid_signup_checkouts == {}


async def test_new_acceptance_marker_is_not_proof_that_an_old_creator_cannot_dispatch(
    authed_client, coupons, fake_billing, fixed_clock, db_session_maker, monkeypatch, db, tmp_path
):
    fake_billing.clock = fixed_clock
    fake_billing.fail_on.add("list_paid_signup_checkouts")
    free, request, _ = await open_paid_signup(authed_client, coupons)
    operation = await db.scalar(
        select(PaidSignup).where(PaidSignup.operation_id == request["operation_id"])
    )
    fake_billing.fail_on.clear()
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    legacy = await fake_billing.create_paid_signup_checkout(
        customer_id=operation.customer_id,
        user_id=operation.user_id,
        operation_id=operation.id,
        price_id=operation.offer["price_id"],
        first_payment_at=datetime.fromisoformat(operation.offer["first_payment_at"]),
        expires_at=datetime.fromisoformat(operation.offer["checkout_expires_at"]),
    )
    fake_billing.hosted_checkouts[legacy.id] = HostedCheckout(
        id=legacy.id,
        status="open",
        customer_id=operation.customer_id,
        user_id=operation.user_id,
        mode="subscription",
        payment_status="unpaid",
        success_url=settings.billing_page_url(),
        cancel_url=settings.billing_page_url(),
        metadata={"pumpkit_paid_signup": operation.id},
        managed_payments=False,
    )
    proof = {
        "request_reference": "controlled-old-worker-read-new-accepted-row-after-fence",
        "creator": "recovery-cli",
        "parameters_sha256": hashlib.sha256(b"controlled-old-request").hexdigest(),
        "relationship_evidence": "controlled-old-code-read-the-new-operation",
        "outcome_evidence": "old-worker-lifetime-not-proven-finished",
        "outcome": "unknown",
    }
    evidence = review(tmp_path / "review.json", closed["binding"], requests=[proof])
    code, result = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 1
    assert "legacy_request_unresolved" in result["blockers"]
    assert fake_billing.expired_hosted_checkouts == []
    assert fake_billing.checkout_dispatches == {}
    assert (await fake_billing.read_checkout(session_id=legacy.id)).status == "open"
    assert (await authed_client.get("/api/v1/billing/me")).json()["free_access"]["ends_at"] == free[
        "ends_at"
    ]


@pytest.mark.parametrize("kind", ["subscription", "top_up", "arranged_paid_signup"])
async def test_proven_preexecution_rejection_allows_fresh_purchase_and_account_deletion(
    authed_client, coupons, fake_billing, fixed_clock, monkeypatch, sells_top_ups, kind
):
    fake_billing.clock = fixed_clock
    free = None
    if kind != "subscription":
        free = await redeem_coupon(authed_client, coupons)
    keys = []

    def create(params, options):
        keys.append(options["idempotency_key"])
        raise stripe.InvalidRequestError(
            "Controlled validation failure", "missing", code="parameter_missing", http_status=400
        )

    sdk = SimpleNamespace(
        v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create=create)))
    )
    adapter = StripeBillingGateway(client=cast(Any, sdk))
    original = fake_billing.dispatch_checkout
    monkeypatch.setattr(fake_billing, "dispatch_checkout", adapter.dispatch_checkout)
    if kind == "arranged_paid_signup":
        request, result = await accept_paid_signup(authed_client)
        assert result["status"] == "refused"
        assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
            "status"
        ] == "refused"
        assert free is not None
        assert (await authed_client.get("/api/v1/billing/me")).json()["free_access"][
            "ends_at"
        ] == free["ends_at"]
        monkeypatch.setattr(fake_billing, "dispatch_checkout", original)
        preview = (
            await authed_client.post(SIGNUPS + "/preview", json={"plan_key": "pumpkit_pro_monthly"})
        ).json()
        replacement = {
            **request,
            "operation_id": "22222222-2222-4222-8222-222222222222",
            "revision": preview["revision"],
        }
        fresh = await authed_client.post(SIGNUPS, json=replacement)
        assert fresh.status_code == 200
        assert fresh.json()["status"] == "pending"
        assert fresh.json()["url"]
        assert (await authed_client.post(SIGNUPS, json=request)).json()["status"] == "refused"
        assert all(key != keys[0] for key in fake_billing.checkout_dispatches)
    else:
        path = CHECKOUT if kind == "subscription" else TOP_UP_CHECKOUT
        payload = CHECKOUT_MONTHLY if kind == "subscription" else ACCEPTANCE
        assert (await authed_client.post(path, json=payload)).status_code == 502
        monkeypatch.setattr(fake_billing, "dispatch_checkout", original)
        assert (await authed_client.post(path, json=payload)).status_code == 200
    assert len(keys) == 1
    assert (
        await authed_client.request("DELETE", "/api/v1/users/me", json={"handle": "ada"})
    ).status_code == 204


@pytest.mark.parametrize("kind", ["subscription", "top_up", "arranged_paid_signup"])
@pytest.mark.parametrize("checkpoint_available", [True, False])
async def test_failed_revalidation_transaction_before_create_does_not_pin_purchase(
    authed_client,
    coupons,
    fake_billing,
    fixed_clock,
    monkeypatch,
    sells_top_ups,
    kind,
    checkpoint_available,
):
    fake_billing.clock = fixed_clock
    if kind != "subscription":
        await redeem_coupon(authed_client, coupons)
    path = CHECKOUT if kind == "subscription" else TOP_UP_CHECKOUT
    armed = False
    failed = False

    def arm(db):
        nonlocal armed
        if any(
            isinstance(row, CheckoutDispatch) and not row.provider_finished
            for row in db.identity_map.values()
        ):
            armed = True

    def fail_read(execute_state):
        nonlocal failed
        if armed and not failed and execute_state.is_select:
            failed = True
            execute_state.session.add(
                CheckoutDispatch(
                    id="controlled-invalid-row",
                    kind="subscription",
                    generation=0,
                    parameters={},
                    idempotency_key="controlled-invalid-key",
                    attempted_at=fixed_clock(),
                )
            )
            execute_state.session.flush()

    def fail_acknowledgement(db):
        if not checkpoint_available and any(
            isinstance(row, CheckoutDispatch) and row.settled for row in db.identity_map.values()
        ):
            raise SQLAlchemyError("Controlled no-dispatch acknowledgement failure")

    event.listen(Session, "after_commit", arm)
    event.listen(Session, "do_orm_execute", fail_read)
    event.listen(Session, "before_commit", fail_acknowledgement)
    try:
        if kind == "arranged_paid_signup":
            preview = (
                await authed_client.post(
                    SIGNUPS + "/preview", json={"plan_key": "pumpkit_pro_monthly"}
                )
            ).json()
            payload = {
                "operation_id": "11111111-1111-4111-8111-111111111111",
                "revision": preview["revision"],
                "terms_version": preview["terms_version"],
                "accepted_terms": True,
                "requested_immediate_start": True,
                "approved_specific_clauses": True,
                "language": "en",
            }
            result = await authed_client.post(SIGNUPS, json=payload)
        else:
            path = CHECKOUT if kind == "subscription" else TOP_UP_CHECKOUT
            payload = CHECKOUT_MONTHLY if kind == "subscription" else ACCEPTANCE
            result = await authed_client.post(path, json=payload)
    finally:
        event.remove(Session, "after_commit", arm)
        event.remove(Session, "do_orm_execute", fail_read)
        event.remove(Session, "before_commit", fail_acknowledgement)
    assert result.status_code == 500
    assert failed
    assert fake_billing.checkouts == []
    if not checkpoint_available:
        if kind == "arranged_paid_signup":
            assert (await authed_client.get(SIGNUPS + "/" + payload["operation_id"])).json()[
                "status"
            ] == "pending"
        else:
            assert (await authed_client.post(path, json=payload)).status_code == 409
        assert (
            await authed_client.request("DELETE", "/api/v1/users/me", json={"handle": "ada"})
        ).status_code == 409
        return
    if kind == "arranged_paid_signup":
        assert (await authed_client.get(SIGNUPS + "/" + payload["operation_id"])).json()[
            "status"
        ] == "refused"
        assert (
            await authed_client.post(SIGNUPS + "/preview", json={"plan_key": "pumpkit_pro_monthly"})
        ).status_code == 200
    else:
        assert (await authed_client.post(path, json=payload)).status_code == 200
    assert (
        await authed_client.request("DELETE", "/api/v1/users/me", json={"handle": "ada"})
    ).status_code == 204


async def test_operator_positive_no_object_proof_ends_arranged_signup_without_replaying_key(
    authed_client, coupons, fake_billing, fixed_clock, db_session_maker, monkeypatch, tmp_path
):
    fake_billing.clock = fixed_clock
    free = await redeem_coupon(authed_client, coupons)
    sent = []

    async def incident(**kwargs):
        sent.append(kwargs)
        raise CheckoutOutcomeUnknown("Controlled provider result requires resolution")

    monkeypatch.setattr(fake_billing, "dispatch_checkout", incident)
    request, result = await accept_paid_signup(authed_client)
    assert result["status"] == "pending"
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    original = sent[0]
    resolution = {
        "dispatch_id": original["parameters"]["metadata"]["pumpkit_dispatch"],
        "parameters_sha256": hashlib.sha256(
            json.dumps(original["parameters"], sort_keys=True).encode()
        ).hexdigest(),
        "idempotency_key_sha256": hashlib.sha256(original["idempotency_key"].encode()).hexdigest(),
        "worker_resolution_evidence": "controlled-worker-returned-with-no-delayed-work",
        "provider_resolution_evidence": "controlled-provider-confirmed-original-request-no-object",
        "outcome": "provider_resolved_no_object",
    }
    evidence = review(tmp_path / "review.json", closed["binding"], resolutions=[resolution])
    code, resolved = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 0, resolved
    assert resolved["ready"] is True
    assert (await authed_client.get(SIGNUPS + "/" + request["operation_id"])).json()[
        "status"
    ] == "refused"
    assert (await authed_client.get("/api/v1/billing/me")).json()["free_access"]["ends_at"] == free[
        "ends_at"
    ]
    assert len(sent) == 1


async def test_replay_preexecution_rejection_cannot_prove_original_key_created_nothing(
    authed_client, fake_billing, fixed_clock, db_session_maker, monkeypatch, tmp_path
):
    fake_billing.plans = [MONTHLY]
    fake_billing.fail_on.add("create_subscription_checkout")
    assert (await authed_client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 502
    fake_billing.fail_on.clear()
    sent = []

    def create(params, options):
        sent.append(options["idempotency_key"])
        raise stripe.AuthenticationError("Controlled authentication rejection", http_status=401)

    sdk = SimpleNamespace(
        v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create=create)))
    )
    adapter = StripeBillingGateway(client=cast(Any, sdk))
    monkeypatch.setattr(fake_billing, "dispatch_checkout", adapter.dispatch_checkout)
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    evidence = review(tmp_path / "review.json", closed["binding"])
    for _ in range(2):
        code, unresolved = await drain(
            db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
        )
        assert code == 1
        assert unresolved["unresolved_dispatches"]
        assert unresolved["ready"] is False
    assert len(sent) == 1
    assert sent[0] in fake_billing.checkout_dispatches
    assert fake_billing.checkouts == []
    assert (
        await authed_client.request("DELETE", "/api/v1/users/me", json={"handle": "ada"})
    ).status_code == 409
