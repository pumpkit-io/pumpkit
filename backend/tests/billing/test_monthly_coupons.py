from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import StringIO

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from alembic import command
from pumpkit.account_deletion import run_cli
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.billing.coupons import run_cli as coupon_cli
from pumpkit.billing.gateway import SubscriptionState
from pumpkit.core.config import settings
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_top_ups import _send
from tests.migrations import migrate
from tests.posts.writing_replies import written


async def monthly(db, user, fake_billing, fixed_clock):
    user.stripe_customer_id = "cus_monthly"
    await db.commit()
    state = SubscriptionState(
        id="sub_monthly",
        status="active",
        price_id="price_monthly",
        plan_key="pumpkit_pro_monthly",
        created_at=fixed_clock() - timedelta(days=15),
        current_period_end=fixed_clock() + timedelta(days=15),
        billing_cycle_anchor=fixed_clock() - timedelta(days=15),
        latest_invoice_status="paid",
        item_id="si_monthly",
        item_count=1,
        interval="month",
        interval_count=1,
        billing_mode="classic",
        current_period_start=fixed_clock() - timedelta(days=15),
        paid_current_period=True,
    )
    fake_billing.set_subscription(user.stripe_customer_id, state)
    return state


async def test_monthly_claim_keeps_paid_allowance_and_queues_free_time(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    state = await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1")
    response = await authed_client.post(PREVIEW, json={"code": created["code"]})
    assert response.status_code == 200, response.text
    offer = response.json()
    assert state.current_period_end is not None
    assert offer["starts_at"] == state.current_period_end.isoformat().replace("+00:00", "Z")
    assert offer["next_payment_at"] == offer["ends_at"]
    response = await authed_client.post(REDEEM, json=confirmation(offer))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    usage = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert usage["generations"]["limit"] == 500
    assert usage["resets_at"] == offer["starts_at"]
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["free_access"]["current_starts_at"] is None
    assert me["free_access"]["queued_starts_at"] == offer["starts_at"]
    assert me["subscription"]["current_period_end"] == offer["ends_at"]
    assert len(fake_billing.deferrals) == 1


async def test_lost_response_recovers_once_after_restart_disabled_and_expired_preview(
    authed_client, coupons, db, user, fake_billing, fixed_clock, monkeypatch, db_session_maker
):

    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    fake_billing.fail_on.add("after_defer_renewal")
    result = await authed_client.post(REDEEM, json=confirmation(offer))
    assert result.json()["status"] == "pending"
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["pending_coupon_operation_id"] == "redeem-test-0001"
    await coupons(created["id"], command="disable")
    fixed_clock.advance(timedelta(days=2))
    monkeypatch.setattr(settings, "COUPONS_ENABLED", False)
    fake_billing.fail_on.clear()
    recovered = await authed_client.get(REDEEM + "/redeem-test-0001")
    assert recovered.json()["status"] == "completed", recovered.text
    assert len(fake_billing.deferrals) == 1
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json() == recovered.json()
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 1


async def test_rejected_retry_keeps_unknown_deferral_and_capacity_reserved(
    authed_client, coupons, db, user, fake_billing, fixed_clock, new_browser, sign_in_for_test
):
    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    fake_billing.fail_on.add("defer_renewal")
    result = await authed_client.post(REDEEM, json=confirmation(offer))
    assert result.json()["status"] == "pending"
    other = new_browser()
    signed = await sign_in_for_test(other, "other@example.com")
    other.headers["Authorization"] = "Bearer " + signed.access_token
    assert (await other.post(PREVIEW, json={"code": created["code"]})).status_code == 409
    assert (await other.get(REDEEM + "/redeem-test-0001")).status_code == 404
    fake_billing.fail_on = {"refuse_deferral"}
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "pending"
    assert (await other.post(PREVIEW, json={"code": created["code"]})).status_code == 409
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0


async def test_pending_blocks_other_billing_and_deletion_then_cancellation_preserves_time(
    authed_client, coupons, db, user, fake_billing, fixed_clock, db_session_maker, file_storage
):

    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    fake_billing.fail_on.add("after_defer_renewal")
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "pending"
    for path in (
        "/api/v1/billing/subscribe-now",
        "/api/v1/billing/portal",
        "/api/v1/billing/cancel-renewal",
    ):
        assert (await authed_client.post(path)).status_code == 409
    err = StringIO()
    assert (
        await run_cli(
            ["--user-id", user.id],
            sessions=db_session_maker,
            gateway=fake_billing,
            storage=file_storage,
            stdout=StringIO(),
            stderr=err,
        )
        == 1
    )
    assert "confirmed" in err.getvalue()
    fake_billing.fail_on.clear()
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "completed"
    assert (await authed_client.post("/api/v1/billing/subscribe-now")).status_code == 409
    assert (await authed_client.post("/api/v1/billing/portal")).status_code == 200
    assert fake_billing.restricted_portals == ["cus_monthly"]
    cancelled = await authed_client.post("/api/v1/billing/cancel-renewal")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["subscription"]["cancel_at"] == offer["ends_at"]
    assert cancelled.json()["subscribed"]
    assert len(fake_billing.deferrals) == 1


async def test_absolute_recovery_never_overwrites_later_or_ended_provider_state(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    state = await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    fake_billing.fail_on.add("defer_renewal")
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "pending"
    fake_billing.fail_on.clear()
    assert state.current_period_end is not None
    fake_billing.set_subscription(
        "cus_monthly",
        replace(state, current_period_end=state.current_period_end + timedelta(days=100)),
    )
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "pending"
    fake_billing.set_subscription(
        "cus_monthly",
        replace(
            state,
            status="canceled",
            current_period_end=state.current_period_end + timedelta(days=100),
        ),
    )
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "pending"
    assert fake_billing.deferrals == []
    fixed_clock.advance(timedelta(days=100))
    fake_billing.set_subscription("cus_monthly", state)
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "pending"
    assert fake_billing.deferrals == []


async def test_month_end_paid_usage_and_accepted_caps_survive_webhooks_and_stacking(
    authed_client,
    coupons,
    db,
    user,
    fake_billing,
    fixed_clock,
    monkeypatch,
    fake_x_reader,
    fake_llm,
):
    fixed_clock.advance(datetime(2028, 2, 10, 12, tzinfo=timezone.utc) - fixed_clock())
    state = await monthly(db, user, fake_billing, fixed_clock)
    fake_billing.set_subscription(
        "cus_monthly",
        replace(
            state,
            current_period_start=datetime(2028, 1, 31, 12, tzinfo=timezone.utc),
            billing_cycle_anchor=datetime(2028, 1, 31, 12, tzinfo=timezone.utc),
            current_period_end=datetime(2028, 2, 29, 12, tzinfo=timezone.utc),
        ),
    )
    created = await coupons("--months", "1")
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(post_id="monthly-author", text="An example", posted_at=fixed_clock())
    ]
    # A provider nudge establishes access before the first write.
    await _send(
        authed_client,
        fake_billing,
        "evt_paid",
        "customer.subscription.updated",
        {"customer": "cus_monthly"},
    )
    await authed_client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    fake_llm.replies = [written("Sketch"), {"post": "Paid allowance survives redemption"}]
    assert (await authed_client.post("/api/v1/posts", json={"brief": "A note"})).status_code == 201
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    assert offer["starts_at"] == "2028-02-29T12:00:00Z"
    assert offer["ends_at"] == "2028-03-31T12:00:00Z"
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "completed"
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 800)
    await _send(
        authed_client,
        fake_billing,
        "evt_delayed_paid",
        "customer.subscription.updated",
        {"customer": "cus_monthly", "status": "active"},
    )
    paid = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert paid["generations"] == {"limit": 500, "used": 1, "left": 499}
    second = await coupons("--months", "1")
    next_offer = (await authed_client.post(PREVIEW, json={"code": second["code"]})).json()
    assert next_offer["ends_at"] == "2028-04-30T12:00:00Z"
    assert (
        await authed_client.post(REDEEM, json=confirmation(next_offer, "second-monthly-0001"))
    ).json()["status"] == "completed"
    fixed_clock.advance(datetime(2028, 2, 29, 12, tzinfo=timezone.utc) - fixed_clock())
    first_free = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert first_free["generations"] == {"limit": 500, "used": 0, "left": 500}
    assert first_free["resets_at"] == "2028-03-31T12:00:00Z"
    fixed_clock.advance(timedelta(days=31))
    second_free = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert second_free["generations"] == {"limit": 800, "used": 0, "left": 800}
    assert second_free["resets_at"] == "2028-04-30T12:00:00Z"


async def test_commit_failure_leaves_durable_intent_for_production_recovery(
    authed_client, coupons, db, user, fake_billing, fixed_clock, db_session_maker, monkeypatch
):
    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    failed = False

    def fail_completion(session):
        nonlocal failed
        if fake_billing.deferrals and not failed:
            failed = True
            raise RuntimeError("Process lost its database commit")

    event.listen(Session, "before_commit", fail_completion)
    try:
        result = await authed_client.post(REDEEM, json=confirmation(offer))
        assert result.status_code == 500
    finally:
        event.remove(Session, "before_commit", fail_completion)
    assert failed
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0
    monkeypatch.setattr(settings, "COUPONS_ENABLED", False)
    out, err = StringIO(), StringIO()
    status = await coupon_cli(
        ["recover"],
        sessions=db_session_maker,
        config=settings,
        gateway=fake_billing,
        clock=fixed_clock,
        stdout=out,
        stderr=err,
    )
    assert status == 0, err.getvalue()
    assert "completed" in out.getvalue()
    assert "cus_monthly" not in out.getvalue()
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "completed"
    assert len(fake_billing.deferrals) == 1


async def test_purge_preserves_unresolved_reservation_and_recovery_after_deadline(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "6")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    fake_billing.fail_on.add("after_defer_renewal")
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "pending"
    await coupons(created["id"], command="disable")
    fixed_clock.advance(timedelta(days=100))
    await coupons(command="purge")
    fake_billing.fail_on.clear()
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "completed"
    assert len(fake_billing.deferrals) == 1
    fixed_clock.advance(timedelta(days=200))
    await coupons(command="purge")
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).status_code == 404


async def test_paid_saved_fields_migrate_without_changing_existing_cardless_access(
    authed_client, coupons, db_engine
):
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    request = confirmation(offer)
    result = (await authed_client.post(REDEEM, json=request)).json()
    before = (await authed_client.get("/api/v1/billing/me")).json()
    await migrate(db_engine, lambda config: command.stamp(config, "head"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0046"))
    await migrate(db_engine, lambda config: command.upgrade(config, "head"))
    assert (await authed_client.get("/api/v1/billing/me")).json() == before
    assert (await authed_client.post(REDEEM, json=request)).json() == result


async def test_cancelled_during_uncertain_deferral_keeps_earned_paid_and_free_time(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    fake_billing.fail_on.add("after_defer_renewal")
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "pending"
    deferred = (await fake_billing.list_subscriptions(customer_id="cus_monthly"))[0]
    fake_billing.set_subscription(
        "cus_monthly", replace(deferred, status="canceled", cancel_at=fixed_clock())
    )
    fake_billing.fail_on.clear()
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "completed"
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["status"] == "canceled"
    assert me["subscribed"] is True
    assert me["free_access"]["current_starts_at"] is None
    assert (await authed_client.get("/api/v1/usage")).json()["allowance"]["generations"][
        "limit"
    ] == 500
    fixed_clock.advance(timedelta(days=15))
    assert (await authed_client.get("/api/v1/billing/me")).json()["subscribed"] is True
    assert (await authed_client.get("/api/v1/usage")).json()["allowance"]["generations"][
        "limit"
    ] == 500


async def test_delayed_duplicate_webhooks_complete_uncertain_mutation_without_reissuing_it(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    fake_billing.fail_on.add("after_defer_renewal")
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "pending"
    fake_billing.fail_on.clear()
    for event_id in ("evt_older_active", "evt_older_active", "evt_later_trial"):
        assert (
            await _send(
                authed_client,
                fake_billing,
                event_id,
                "customer.subscription.updated",
                {"customer": "cus_monthly", "status": "active"},
            )
        ).status_code == 200
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["pending_coupon_operation"] is False
    assert me["subscription"]["status"] == "trialing"
    assert me["subscription"]["current_period_end"] == offer["ends_at"]
    assert me["free_access"]["months"] == 1
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 1
    assert len(fake_billing.deferrals) == 1


async def test_refused_operation_audit_expires_after_resolution_without_a_benefit(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "12")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    fake_billing.fail_on.add("refuse_deferral")
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "refused"
    fixed_clock.advance(timedelta(days=91))
    await coupons(command="purge")
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).status_code == 404
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0


@pytest.fixture
async def user(legacy_user):
    return legacy_user
