import asyncio
import threading
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.billing.gateway import (
    HostedCheckout,
    PaidSignupCheckout,
    StripeBillingGateway,
    SubscriptionState,
)
from pumpkit.billing.models import CheckoutDispatch, CheckoutFence
from pumpkit.core.config import settings
from tests.billing.checkout_drain import drain, review
from tests.billing.paid_signups import SIGNUPS, redeem_coupon
from tests.billing.postgres.test_coupon_contention import wait_for_locks
from tests.billing.test_billing import CHECKOUT, CHECKOUT_MONTHLY, MONTHLY
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_top_ups import ACCEPTANCE, TOP_UP_CHECKOUT
from tests.billing.test_top_ups import sells_top_ups as sells_top_ups

pytestmark = pytest.mark.postgres


async def purchase_request(client, coupons, kind):
    if kind != "subscription":
        await redeem_coupon(client, coupons)
    if kind == "subscription":
        return CHECKOUT, CHECKOUT_MONTHLY
    if kind == "top_up":
        return TOP_UP_CHECKOUT, ACCEPTANCE
    offer = (
        await client.post(SIGNUPS + "/preview", json={"plan_key": "pumpkit_pro_monthly"})
    ).json()
    return SIGNUPS, {
        "operation_id": "11111111-1111-4111-8111-111111111111",
        "revision": offer["revision"],
        "terms_version": offer["terms_version"],
        "accepted_terms": True,
        "requested_immediate_start": True,
        "approved_specific_clauses": True,
        "language": "en",
    }


@pytest.mark.parametrize("kind", ["subscription", "top_up", "arranged_paid_signup"])
async def test_cancelled_request_keeps_provider_worker_owned_until_late_checkout_is_drained(
    client,
    fake_billing,
    db_session_maker,
    monkeypatch,
    tmp_path,
    fixed_clock,
    coupons,
    sells_top_ups,
    kind,
):
    fake_billing.clock = fixed_clock
    path, payload = await purchase_request(client, coupons, kind)
    if kind == "arranged_paid_signup":

        async def signup_checkouts(*, customer_id):
            return [
                PaidSignupCheckout(
                    id=s.id,
                    customer_id=customer_id,
                    operation_id=s.metadata["pumpkit_paid_signup"],
                    status=s.status,
                    url=s.url,
                )
                for s in fake_billing.hosted_checkouts.values()
                if s.customer_id == customer_id
            ]

        monkeypatch.setattr(fake_billing, "list_paid_signup_checkouts", signup_checkouts)
    entered, finish = threading.Event(), threading.Event()
    original = fake_billing.dispatch_checkout

    def create(params, options):
        entered.set()
        assert finish.wait(10)
        fake_billing.hosted_checkouts["cs_threaded"] = HostedCheckout(
            id="cs_threaded",
            status="open",
            customer_id=params["customer"],
            user_id=params["client_reference_id"],
            mode=params["mode"],
            payment_status="unpaid",
            success_url=params["success_url"],
            cancel_url=params["cancel_url"],
            metadata=params["metadata"],
            managed_payments=False,
            url="https://checkout.test/threaded",
        )
        return SimpleNamespace(id="cs_threaded", url="https://checkout.test/threaded")

    sdk = SimpleNamespace(
        v1=SimpleNamespace(checkout=SimpleNamespace(sessions=SimpleNamespace(create=create)))
    )
    adapter = StripeBillingGateway(client=cast(Any, sdk))
    monkeypatch.setattr(fake_billing, "dispatch_checkout", adapter.dispatch_checkout)
    request = asyncio.create_task(client.post(path, json=payload))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        request.cancel()
        monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
        _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
        evidence = review(tmp_path / "review.json", closed["binding"])
        code, busy = await drain(
            db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
        )
        assert code == 1
        assert busy["ready"] is False
        assert "dispatch_unresolved" in busy["blockers"]
        assert fake_billing.expired_hosted_checkouts == []
        assert not request.done()
    finally:
        finish.set()
        await asyncio.gather(request, return_exceptions=True)
        monkeypatch.setattr(fake_billing, "dispatch_checkout", original)
    code, final = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 0, final
    assert final["ready"] is True
    assert fake_billing.expired_hosted_checkouts == ["cs_threaded"]
    assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 503


@pytest.mark.parametrize("kind", ["subscription", "top_up", "arranged_paid_signup"])
async def test_committed_intent_gap_stays_unready_until_original_caller_acknowledges_pause(
    client,
    fake_billing,
    db_session_maker,
    monkeypatch,
    tmp_path,
    fixed_clock,
    coupons,
    sells_top_ups,
    kind,
):

    fake_billing.clock = fixed_clock
    path, payload = await purchase_request(client, coupons, kind)
    committed, resume = asyncio.Event(), asyncio.Event()
    commit = AsyncSession.commit
    request = None

    async def commit_with_dispatch_gap(db):
        registered = any(isinstance(row, CheckoutDispatch) for row in db.identity_map.values())
        await commit(db)
        if asyncio.current_task() is request and registered and not committed.is_set():
            committed.set()
            await resume.wait()

    monkeypatch.setattr(AsyncSession, "commit", commit_with_dispatch_gap)
    request = asyncio.create_task(client.post(path, json=payload))
    try:
        await asyncio.wait_for(committed.wait(), 3)
        monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
        _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
        evidence = review(tmp_path / "review.json", closed["binding"])
        code, busy = await drain(
            db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
        )
        assert code == 1
        assert "dispatch_unresolved" in busy["blockers"]
        assert fake_billing.checkouts == []
    finally:
        resume.set()
        response = await request
    assert response.status_code == 503
    code, final = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    if kind == "arranged_paid_signup":
        operation = await client.get(SIGNUPS + "/" + payload["operation_id"])
        assert operation.json()["status"] == "refused"
    assert code == 0, final
    assert final["ready"] is True
    assert fake_billing.checkouts == []


async def test_closed_fence_blocks_selected_verification_until_explicit_release(
    client, fake_billing, db_session_maker, monkeypatch, tmp_path, fixed_clock, user
):
    fake_billing.plans = [MONTHLY]
    monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
    _, closed = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    evidence = review(tmp_path / "review.json", closed["binding"])
    code, ready = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 0, ready
    monkeypatch.setattr(settings, "STRIPE_MANAGED_PAYMENTS", True)
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", user.id)
    assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 503
    _, target = await drain(
        db_session_maker, fake_billing, ["status", *evidence], clock=fixed_clock
    )
    args = [
        "release",
        *evidence,
        "--receipt",
        ready["receipt"],
        "--generation",
        str(ready["fence"]["generation"]),
        "--target-fingerprint",
        target["current_config_fingerprint"],
    ]
    code, released = await drain(db_session_maker, fake_billing, args, clock=fixed_clock)
    assert code == 0, released
    assert released["fence"]["closed"] is False
    assert released["fence"]["generation"] == ready["fence"]["generation"] + 1
    assert (await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 200
    assert next(iter(fake_billing.checkout_dispatches.values()))["managed_payments"] == {
        "enabled": True
    }
    code, replayed = await drain(db_session_maker, fake_billing, args, clock=fixed_clock)
    assert code == 0 and replayed["release_replayed"] is True
    assert replayed["fence"] == released["fence"]
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", None)
    _, recaptured = await drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
    monkeypatch.setattr(settings, "BILLING_VERIFICATION_USER_ID", user.id)
    code, stale = await drain(db_session_maker, fake_billing, args, clock=fixed_clock)
    assert code == 1
    assert "release_binding_invalid" in stale["blockers"]
    assert stale["fence"] == recaptured["fence"]


async def test_subscription_eligibility_is_revalidated_after_durable_intent_releases_user_lock(
    client, fake_billing, db_session_maker, monkeypatch, fixed_clock
):

    committed, resume = asyncio.Event(), asyncio.Event()
    commit = AsyncSession.commit
    request = None

    async def commit_with_dispatch_gap(db):
        registered = any(isinstance(row, CheckoutDispatch) for row in db.identity_map.values())
        await commit(db)
        if asyncio.current_task() is request and registered and not committed.is_set():
            committed.set()
            await resume.wait()

    monkeypatch.setattr(AsyncSession, "commit", commit_with_dispatch_gap)
    fake_billing.plans = [MONTHLY]
    request = asyncio.create_task(client.post(CHECKOUT, json=CHECKOUT_MONTHLY))
    try:
        await asyncio.wait_for(committed.wait(), 3)
        fake_billing.set_subscription(
            "cus_fake_1",
            SubscriptionState(
                id="sub_paid_while_waiting",
                status="active",
                price_id="price_monthly",
                plan_key=MONTHLY.key,
                created_at=fixed_clock(),
                current_period_end=fixed_clock() + timedelta(days=30),
            ),
        )
    finally:
        resume.set()
        response = await request
    assert response.status_code == 409
    assert fake_billing.checkouts == []
    assert (await client.get("/api/v1/billing/me")).json()["subscribed"] is True


async def test_checkout_registration_and_fence_closure_contend_without_late_provider_dispatch(
    client, fake_billing, fixed_clock, db_session_maker, db_engine, monkeypatch, tmp_path, db
):
    db.add(
        CheckoutFence(
            id=1, instance_id="controlled-contention-instance", generation=0, closed=False
        )
    )
    await db.commit()
    fake_billing.plans = [MONTHLY]
    async with db_session_maker() as control:
        await control.scalar(select(CheckoutFence).where(CheckoutFence.id == 1).with_for_update())
        request = asyncio.create_task(client.post(CHECKOUT, json=CHECKOUT_MONTHLY))
        await wait_for_locks(db_engine, 1)
        monkeypatch.setattr(settings, "BILLING_PURCHASES_PAUSED", True)
        closing = asyncio.create_task(
            drain(db_session_maker, fake_billing, ["execute"], clock=fixed_clock)
        )
        await wait_for_locks(db_engine, 2)
        await control.commit()
        response, (_, closed) = await asyncio.wait_for(asyncio.gather(request, closing), 10)
    assert response.status_code == 503
    assert closed["fence"]["closed"] is True
    assert fake_billing.checkouts == []
    evidence = review(tmp_path / "review.json", closed["binding"])
    code, ready = await drain(
        db_session_maker, fake_billing, ["execute", *evidence], clock=fixed_clock
    )
    assert code == 0, ready
    assert ready["ready"] is True
    assert fake_billing.checkouts == []
