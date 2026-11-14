from dataclasses import replace
from datetime import datetime, timedelta
from io import StringIO

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from pumpkit.account_deletion import run_cli as delete_cli
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.billing.allowance import months_after
from pumpkit.billing.gateway import Plan
from pumpkit.billing.models import PlanChange
from pumpkit.billing.plan_change_recovery import run_cli
from pumpkit.billing.terms import TERMS_VERSION
from pumpkit.core.config import settings
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_monthly_coupons import monthly
from tests.billing.test_paid_signups import SIGNUPS, _open
from tests.billing.test_paid_signups import billing_clock as billing_clock
from tests.billing.test_top_ups import _send
from tests.positioning.positioning import save_positioning

CHANGES = "/api/v1/billing/plan-changes"


@pytest.fixture(autouse=True)
def both_plans(coupons, monkeypatch, fake_billing):
    monkeypatch.setattr(
        settings, "BILLING_PLAN_KEYS", ["pumpkit_pro_monthly", "pumpkit_pro_annual"]
    )
    fake_billing.plans.append(
        Plan("pumpkit_pro_annual", "price_annual", "Pro", 20000, "eur", "year", 1)
    )


@pytest.mark.parametrize("interval", ["month", "year"])
async def test_change_payment_interval_preserves_earned_time_and_usage(
    authed_client, coupons, db, user, fake_billing, fixed_clock, interval
):
    original = await monthly(db, user, fake_billing, fixed_clock)
    if interval == "year":
        assert original.billing_cycle_anchor is not None
        original = replace(
            original, interval="year", price_id="price_annual", plan_key="pumpkit_pro_annual"
        )
        assert original.billing_cycle_anchor is not None
        original = replace(
            original, current_period_end=months_after(original.billing_cycle_anchor, 12)
        )
        fake_billing.set_subscription(user.stripe_customer_id, original)
    code = await coupons("--months", "2")
    offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "completed"
    usage = (await authed_client.get("/api/v1/usage")).json()
    key = "pumpkit_pro_annual" if interval == "month" else "pumpkit_pro_monthly"
    preview = await authed_client.post(CHANGES + "/preview", json={"plan_key": key})
    assert preview.status_code == 200, preview.text
    proposed = preview.json()
    assert proposed["first_payment_at"] == offer["ends_at"]
    changed = await authed_client.post(
        CHANGES, json={"operation_id": "plan-change-test-0001", "revision": proposed["revision"]}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["status"] == "completed"
    assert changed.json()["plan_key"] == key
    assert (await authed_client.get("/api/v1/usage")).json() == usage
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["free_access"]["ends_at"] == offer["ends_at"]
    assert original.current_period_end is not None
    assert me["subscription"]["paid_through"] == original.current_period_end.isoformat().replace(
        "+00:00", "Z"
    )
    assert me["future_plan"]["plan_key"] == key
    assert me["future_plan"]["first_payment_at"] == offer["ends_at"]


async def deferred(authed_client, coupons, db, user, fake_billing, fixed_clock):
    await monthly(db, user, fake_billing, fixed_clock)
    code = await coupons("--months", "2")
    offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "completed"
    return offer


async def proposed_change(authed_client):
    preview = await authed_client.post(
        CHANGES + "/preview", json={"plan_key": "pumpkit_pro_annual"}
    )
    assert preview.status_code == 200, preview.text
    return {"operation_id": "plan-change-test-0001", "revision": preview.json()["revision"]}


@pytest.mark.parametrize("advance", [False, True])
async def test_switch_then_stack_then_full_annual_renewal_keeps_calendar_and_allowance(
    authed_client, coupons, db, user, fake_billing, fixed_clock, advance
):
    offer = await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    if advance:
        fixed_clock.advance(
            datetime.fromisoformat(offer["starts_at"].replace("Z", "+00:00")) - fixed_clock()
        )
    before = (await authed_client.get("/api/v1/usage")).json()
    changed = await authed_client.post(CHANGES, json=await proposed_change(authed_client))
    assert changed.json()["status"] == "completed", changed.text
    assert (await authed_client.get("/api/v1/usage")).json() == before
    next_code = await coupons("--months", "1")
    next_offer = (await authed_client.post(PREVIEW, json={"code": next_code["code"]})).json()
    assert next_offer["starts_at"] == offer["ends_at"]
    claimed = await authed_client.post(
        REDEEM, json={**confirmation(next_offer), "operation_id": "redeem-test-0002"}
    )
    assert claimed.json()["status"] == "completed", claimed.text
    end = datetime.fromisoformat(next_offer["ends_at"].replace("Z", "+00:00"))
    state = (await fake_billing.list_subscriptions(customer_id=user.stripe_customer_id))[0]
    fixed_clock.advance(end - fixed_clock())
    fake_billing.set_subscription(
        user.stripe_customer_id,
        replace(
            state,
            status="active",
            current_period_start=end,
            current_period_end=months_after(end, 12),
            paid_current_period=True,
        ),
    )
    await _send(
        authed_client,
        fake_billing,
        event_id="evt_annual_renewal",
        event_type="customer.subscription.updated",
        data_object={"customer": user.stripe_customer_id},
    )
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["current_period_end"] == months_after(end, 12).isoformat().replace(
        "+00:00", "Z"
    )
    assert me["free_access"] is None
    usage = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert usage["generations"]["limit"] == 500
    assert usage["resets_at"] == months_after(end, 1).isoformat().replace("+00:00", "Z")


@pytest.mark.parametrize(
    "change",
    [
        {"schedule_id": "sub_sched"},
        {"has_pending_update": True},
        {"cancel_at": "end"},
        {"latest_invoice_status": "open"},
    ],
)
async def test_provider_conflict_after_preview_refuses_without_consuming_coupon_or_writing(
    authed_client, coupons, db, user, fake_billing, fixed_clock, change
):
    await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    code = await coupons("--months", "1")
    coupon_offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    state = (await fake_billing.list_subscriptions(customer_id=user.stripe_customer_id))[0]
    if change.get("cancel_at") == "end":
        change = {"cancel_at": state.trial_end}
    fake_billing.set_subscription(user.stripe_customer_id, replace(state, **change))
    refused = await authed_client.post(CHANGES, json=request)
    assert refused.status_code == 409, refused.text
    if "cancel_at" not in change:
        assert (
            await authed_client.post(REDEEM, json=confirmation(coupon_offer))
        ).status_code == 409
        assert (await coupons(code["id"], command="inspect"))["redeemed_count"] == 0
    assert fake_billing.plan_changes == []
    assert len(fake_billing.deferrals) == 1


async def test_ambiguous_change_recovers_flag_off_and_duplicate_webhook_never_replays(
    authed_client, coupons, db, user, fake_billing, fixed_clock, monkeypatch
):
    await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    fake_billing.fail_on.add("after_change_plan")
    answer = await authed_client.post(CHANGES, json=request)
    assert answer.json()["status"] == "pending"
    for path in (
        "/api/v1/billing/portal",
        "/api/v1/billing/subscribe-now",
        "/api/v1/billing/cancel-renewal",
    ):
        assert (await authed_client.post(path)).status_code == 409
    code = await coupons("--months", "1")
    assert (await authed_client.post(PREVIEW, json={"code": code["code"]})).status_code == 409
    assert (await authed_client.get("/api/v1/billing/me")).json()[
        "pending_plan_change_id"
    ] == request["operation_id"]
    monkeypatch.setattr(settings, "COUPONS_ENABLED", False)
    fake_billing.fail_on.clear()
    for _ in range(2):
        await _send(
            authed_client,
            fake_billing,
            event_id="evt_plan_change",
            event_type="customer.subscription.updated",
            data_object={"customer": user.stripe_customer_id, "plan_key": "old-price"},
        )
    recovered = await authed_client.get(CHANGES + "/" + request["operation_id"])
    assert recovered.json()["status"] == "completed"
    assert len(fake_billing.plan_changes) == 1
    cancelled = await authed_client.post("/api/v1/billing/cancel-renewal")
    assert cancelled.status_code == 200
    assert cancelled.json()["subscription"]["cancel_at"] == recovered.json()["first_payment_at"]
    assert cancelled.json()["future_plan"] is None


@pytest.mark.parametrize("end_reason", ["retention", "cancel", "expiry", "conflict"])
async def test_unknown_change_never_replayed_after_safety_boundary(
    authed_client, coupons, db, user, fake_billing, fixed_clock, end_reason
):
    await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    fake_billing.fail_on.add("change_plan")
    assert (await authed_client.post(CHANGES, json=request)).json()["status"] == "pending"
    fake_billing.fail_on.clear()
    state = (await fake_billing.list_subscriptions(customer_id=user.stripe_customer_id))[0]
    if end_reason == "cancel":
        fake_billing.set_subscription(
            user.stripe_customer_id, replace(state, cancel_at=state.trial_end)
        )
    elif end_reason == "conflict":
        fake_billing.set_subscription(
            user.stripe_customer_id, replace(state, has_pending_update=True)
        )
    else:
        fixed_clock.advance(
            timedelta(hours=23) if end_reason == "retention" else timedelta(days=100)
        )
    assert (await authed_client.get(CHANGES + "/" + request["operation_id"])).json()[
        "status"
    ] == "pending"
    assert fake_billing.plan_changes == []
    assert (await authed_client.post("/api/v1/billing/cancel-renewal")).status_code == 409


async def test_uncertain_unsent_change_retries_same_intent_before_deadline(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    fake_billing.fail_on.add("change_plan")
    assert (await authed_client.post(CHANGES, json=request)).json()["status"] == "pending"
    fake_billing.fail_on.clear()
    assert (await authed_client.get(CHANGES + "/" + request["operation_id"])).json()[
        "status"
    ] == "completed"
    assert (await authed_client.post(CHANGES, json=request)).json()["status"] == "completed"
    assert len(fake_billing.plan_changes) == 1


async def test_management_portal_and_ordinary_cancel_are_safe_before_later_coupon(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    state = await monthly(db, user, fake_billing, fixed_clock)
    assert (await authed_client.post("/api/v1/billing/portal")).status_code == 200
    assert fake_billing.restricted_portals == [user.stripe_customer_id]
    cancelled = await authed_client.post("/api/v1/billing/cancel-renewal")
    assert cancelled.status_code == 200, cancelled.text
    assert state.current_period_end is not None
    assert cancelled.json()["subscription"][
        "cancel_at"
    ] == state.current_period_end.isoformat().replace("+00:00", "Z")


async def test_recovery_retains_intent_if_process_stops_before_dispatch(
    authed_client, coupons, db, user, fake_billing, fixed_clock, monkeypatch
):
    await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    live = fake_billing.list_subscriptions
    reads = 0

    async def stop_after_intent(**kwargs):
        nonlocal reads
        reads += 1
        if reads == 2:
            raise RuntimeError("process stopped")
        return await live(**kwargs)

    monkeypatch.setattr(fake_billing, "list_subscriptions", stop_after_intent)
    assert (await authed_client.post(CHANGES, json=request)).status_code == 500
    monkeypatch.setattr(fake_billing, "list_subscriptions", live)
    assert (await authed_client.get("/api/v1/billing/me")).json()[
        "pending_plan_change_id"
    ] == request["operation_id"]
    assert fake_billing.plan_changes == []
    assert (await authed_client.get(CHANGES + "/" + request["operation_id"])).json()[
        "status"
    ] == "completed"
    assert len(fake_billing.plan_changes) == 1


async def test_final_commit_loss_keeps_recoverable_mutation_and_earned_coverage(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    before = (await authed_client.get("/api/v1/usage")).json()

    def lost_commit(session):
        if fake_billing.plan_changes:
            raise RuntimeError("commit lost")

    event.listen(Session, "before_commit", lost_commit)
    try:
        assert (await authed_client.post(CHANGES, json=request)).status_code == 500
    finally:
        event.remove(Session, "before_commit", lost_commit)
    assert (await authed_client.get("/api/v1/billing/me")).json()[
        "pending_plan_change_id"
    ] == request["operation_id"]
    assert (await authed_client.get(CHANGES + "/" + request["operation_id"])).json()[
        "status"
    ] == "completed"
    assert len(fake_billing.plan_changes) == 1
    assert (await authed_client.get("/api/v1/usage")).json() == before


async def test_original_replay_deadline_checked_after_slow_provider_read(
    authed_client, coupons, db, user, fake_billing, fixed_clock, monkeypatch
):
    await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    fake_billing.fail_on.add("change_plan")
    assert (await authed_client.post(CHANGES, json=request)).json()["status"] == "pending"
    fake_billing.fail_on.clear()
    fixed_clock.advance(timedelta(hours=22, minutes=59))
    live = fake_billing.has_unsettled_invoices

    async def slow_read(**kwargs):
        fixed_clock.advance(timedelta(minutes=1))
        return await live(**kwargs)

    monkeypatch.setattr(fake_billing, "has_unsettled_invoices", slow_read)
    assert (await authed_client.get(CHANGES + "/" + request["operation_id"])).json()[
        "status"
    ] == "pending"
    assert fake_billing.plan_changes == []


@pytest.mark.parametrize("boundary", ["cancel", "changed_end"])
async def test_remote_change_between_dispatch_and_readback_never_revives_cancellation_or_shortens_grants(
    authed_client, coupons, db, user, fake_billing, fixed_clock, monkeypatch, boundary
):
    offer = await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    live = fake_billing.change_plan

    async def concurrent_change(**kwargs):
        await live(**kwargs)
        state = (await fake_billing.list_subscriptions(customer_id=user.stripe_customer_id))[0]
        fake_billing.set_subscription(
            user.stripe_customer_id,
            replace(
                state,
                **(
                    {"cancel_at": state.trial_end}
                    if boundary == "cancel"
                    else {"trial_end": state.trial_end - timedelta(days=1)}
                ),
            ),
        )

    monkeypatch.setattr(fake_billing, "change_plan", concurrent_change)
    result = await authed_client.post(CHANGES, json=request)
    assert result.json()["status"] == ("completed" if boundary == "cancel" else "pending")
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["free_access"]["ends_at"] == offer["ends_at"]
    if boundary == "cancel":
        assert me["subscription"]["cancel_at"] == offer["ends_at"]
        assert me["future_plan"] is None
        assert not me["may_change_plan"]


async def test_provider_calling_recovery_and_cancellation_are_rate_limited_without_effects(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    code = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    fake_billing.fail_on.add("defer_renewal")
    request = {**confirmation(offer), "operation_id": "rate-limit-recovery-0001"}
    assert (await authed_client.post(REDEEM, json=request)).json()["status"] == "pending"
    for _ in range(60):
        assert (await authed_client.get(REDEEM + "/" + request["operation_id"])).status_code == 200
    before = (await authed_client.get("/api/v1/billing/me")).json()
    fake_billing.fail_on.clear()
    assert (await authed_client.get(REDEEM + "/" + request["operation_id"])).status_code == 429
    for _ in range(20):
        assert (await authed_client.post("/api/v1/billing/cancel-renewal")).status_code == 409
    assert (await authed_client.post("/api/v1/billing/cancel-renewal")).status_code == 429
    assert (await authed_client.get("/api/v1/billing/me")).json() == before
    assert len(fake_billing.deferrals) == 1
    assert (await coupons(code["id"], command="inspect"))["redeemed_count"] == 0
    assert (await fake_billing.list_subscriptions(customer_id=user.stripe_customer_id))[
        0
    ].cancel_at is None


async def test_privileged_plan_recovery_works_with_flag_off_and_same_acceptance(
    authed_client, coupons, db, user, fake_billing, fixed_clock, monkeypatch, db_session_maker
):
    await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    fake_billing.fail_on.add("after_change_plan")
    assert (await authed_client.post(CHANGES, json=request)).json()["status"] == "pending"
    monkeypatch.setattr(settings, "COUPONS_ENABLED", False)
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
    assert (await authed_client.get(CHANGES + "/" + request["operation_id"])).json()[
        "status"
    ] == "completed"
    assert len(fake_billing.plan_changes) == 1


async def test_interval_change_keeps_used_generation_and_captured_paid_caps(
    authed_client,
    coupons,
    db,
    user,
    fake_billing,
    fixed_clock,
    fake_x_reader,
    fake_llm,
    monkeypatch,
):
    await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(post_id="plan-author", text="An example", posted_at=fixed_clock())
    ]
    await save_positioning(authed_client)
    assert (
        await authed_client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    ).status_code == 201
    fake_llm.replies = [{"post": "A used generation before changing payment frequency"}]
    assert (await authed_client.post("/api/v1/posts", json={"brief": "A note"})).status_code == 201
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 800)
    before = (await authed_client.get("/api/v1/usage")).json()
    assert before["allowance"]["generations"] == {"limit": 500, "used": 1, "left": 499}
    assert (await authed_client.post(CHANGES, json=await proposed_change(authed_client))).json()[
        "status"
    ] == "completed"
    assert (await authed_client.get("/api/v1/usage")).json() == before


async def test_explicit_future_signup_can_change_frequency_and_redeem_again_without_new_trial(
    authed_client, coupons, fake_billing
):
    free, signup, opened = await _open(authed_client, coupons)
    fake_billing.complete_paid_signup_setup(opened["session_id"])
    assert (await authed_client.get(SIGNUPS + "/" + signup["operation_id"])).json()[
        "status"
    ] == "completed"
    before = (await authed_client.get("/api/v1/usage")).json()
    assert (await authed_client.post(CHANGES, json=await proposed_change(authed_client))).json()[
        "status"
    ] == "completed"
    code = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    assert offer["starts_at"] == free["ends_at"]
    assert (
        await authed_client.post(
            REDEEM, json={**confirmation(offer), "operation_id": "after-signup-change-0001"}
        )
    ).json()["status"] == "completed"
    assert (await authed_client.get("/api/v1/usage")).json() == before
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["introductory_trial_end"] is None
    assert me["subscription"]["paid_through"] is None
    assert me["future_plan"]["first_payment_at"] == offer["ends_at"]


@pytest.mark.parametrize("replay_error", ["plan_change_in_progress", "refuse_plan_change"])
async def test_rejected_replay_keeps_unknown_original_price_write_guarded_until_it_finishes(
    authed_client,
    coupons,
    db,
    user,
    fake_billing,
    fixed_clock,
    db_session_maker,
    file_storage,
    replay_error,
):
    free = await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    code = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    before = (await authed_client.get("/api/v1/usage")).json()
    fake_billing.delay_plan_changes = True
    assert (await authed_client.post(CHANGES, json=request)).json()["status"] == "pending"
    fake_billing.fail_on.add(replay_error)
    retried = await authed_client.get(CHANGES + "/" + request["operation_id"])
    assert retried.json()["status"] == "pending", retried.text
    assert (await authed_client.get("/api/v1/billing/me")).json()[
        "pending_plan_change_id"
    ] == request["operation_id"]
    for path, body in [
        (PREVIEW, {"code": code["code"]}),
        (REDEEM, {**confirmation(offer), "operation_id": "guarded-claim-0001"}),
        (SIGNUPS + "/preview", {"plan_key": "pumpkit_pro_annual"}),
        ("/api/v1/billing/portal", None),
        ("/api/v1/billing/cancel-renewal", None),
        ("/api/v1/billing/subscribe-now", None),
        ("/api/v1/billing/checkout", {"plan_key": "pumpkit_pro_annual"}),
    ]:
        assert (await authed_client.post(path, json=body)).status_code == 409
    err = StringIO()
    assert (
        await delete_cli(
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
    assert (await coupons(code["id"], command="inspect"))["redeemed_count"] == 0
    assert fake_billing.plan_changes == []
    assert (await authed_client.get("/api/v1/usage")).json() == before
    fake_billing.fail_on.clear()
    fake_billing.complete_pending_plan_change(next(iter(fake_billing.pending_plan_changes)))
    answer = await authed_client.get(CHANGES + "/" + request["operation_id"])
    assert answer.json()["status"] == "completed", answer.text
    assert len(fake_billing.plan_changes) == 1
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["free_access"]["ends_at"] == free["ends_at"]
    assert me["future_plan"]["plan_key"] == "pumpkit_pro_annual"
    assert (await authed_client.get("/api/v1/usage")).json() == before


async def test_first_definite_price_refusal_releases_guard_without_consuming_coupon(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    code = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    fake_billing.fail_on.add("refuse_plan_change")
    answer = await authed_client.post(CHANGES, json=request)
    assert answer.json()["status"] == "refused", answer.text
    assert (await authed_client.get("/api/v1/billing/me")).json()["pending_plan_change_id"] is None
    assert (await coupons(code["id"], command="inspect"))["redeemed_count"] == 0
    assert fake_billing.plan_changes == []
    fake_billing.fail_on.clear()
    claimed = await authed_client.post(
        REDEEM, json={**confirmation(offer), "operation_id": "after-refusal-0001"}
    )
    assert claimed.json()["status"] == "completed", claimed.text


async def test_ended_change_history_cannot_price_a_new_explicit_signup_with_same_plan_key(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    free = await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    change = await proposed_change(authed_client)
    old_result = (await authed_client.post(CHANGES, json=change)).json()
    assert old_result["status"] == "completed"
    assert old_result["amount"] == 20000
    fixed_clock.advance(
        datetime.fromisoformat(free["starts_at"].replace("Z", "+00:00")) - fixed_clock()
    )
    original = (await fake_billing.list_subscriptions(customer_id=user.stripe_customer_id))[0]
    await fake_billing.cancel_subscription(subscription_id=original.id)
    await _send(
        authed_client,
        fake_billing,
        "evt_old_change_ended",
        "customer.subscription.deleted",
        {"customer": user.stripe_customer_id},
    )
    fake_billing.plans = [
        replace(plan, price_id="price_new_annual", amount=25000)
        if plan.key == "pumpkit_pro_annual"
        else plan
        for plan in fake_billing.plans
    ]
    proposed = await authed_client.post(
        SIGNUPS + "/preview", json={"plan_key": "pumpkit_pro_annual"}
    )
    assert proposed.status_code == 200, proposed.text
    offer = proposed.json()
    assert offer["amount"] == 25000
    signup = {
        "operation_id": "new-subscription-after-A",
        "revision": offer["revision"],
        "terms_version": offer["terms_version"],
        "accepted_terms": True,
        "requested_immediate_start": True,
        "approved_specific_clauses": True,
        "language": "en",
    }
    opened = await authed_client.post(SIGNUPS, json=signup)
    assert opened.status_code == 200, opened.text
    fake_billing.complete_paid_signup_setup(opened.json()["session_id"])
    assert (await authed_client.get(SIGNUPS + "/" + signup["operation_id"])).json()[
        "status"
    ] == "completed"
    states = await fake_billing.list_subscriptions(customer_id=user.stripe_customer_id)
    current = next(state for state in states if state.status == "trialing")
    assert current.id != original.id
    assert current.price_id == "price_new_annual"
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["plan_key"] == "pumpkit_pro_annual"
    assert me["free_access"]["ends_at"] == free["ends_at"]
    assert me["future_plan"] is None
    assert (await authed_client.get(CHANGES + "/" + change["operation_id"])).json() == old_result


async def test_current_subscription_with_replaced_provider_price_cannot_reuse_accepted_amount(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    change = await proposed_change(authed_client)
    old_result = (await authed_client.post(CHANGES, json=change)).json()
    assert old_result["status"] == "completed"
    original = (await fake_billing.list_subscriptions(customer_id=user.stripe_customer_id))[0]
    fake_billing.set_subscription(
        user.stripe_customer_id, replace(original, price_id="price_new_annual")
    )
    await _send(
        authed_client,
        fake_billing,
        "evt_same_sub_new_price",
        "customer.subscription.updated",
        {"customer": user.stripe_customer_id},
    )
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["plan_key"] == "pumpkit_pro_annual"
    assert me["future_plan"] is None
    assert (await authed_client.get(CHANGES + "/" + change["operation_id"])).json() == old_result


async def test_accepted_current_provider_price_stays_authoritative_after_lookup_key_moves(
    authed_client, coupons, db, user, fake_billing, fixed_clock
):
    free = await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    change = await proposed_change(authed_client)
    old_result = (await authed_client.post(CHANGES, json=change)).json()
    assert old_result["status"] == "completed"
    next_code = await coupons("--months", "1")
    added = (await authed_client.post(PREVIEW, json={"code": next_code["code"]})).json()
    assert added["starts_at"] == free["ends_at"]
    assert (
        await authed_client.post(
            REDEEM, json={**confirmation(added), "operation_id": "extended-current-price-0001"}
        )
    ).json()["status"] == "completed"
    fake_billing.plans = [
        replace(plan, price_id="price_new_annual", amount=25000)
        if plan.key == "pumpkit_pro_annual"
        else plan
        for plan in fake_billing.plans
    ]
    original = (await fake_billing.list_subscriptions(customer_id=user.stripe_customer_id))[0]
    fake_billing.set_subscription(user.stripe_customer_id, replace(original, plan_key=None))
    await _send(
        authed_client,
        fake_billing,
        "evt_old_price_key_moved",
        "customer.subscription.updated",
        {"customer": user.stripe_customer_id},
    )
    catalog = (await authed_client.get("/api/v1/billing/plans")).json()["data"]
    assert next(plan for plan in catalog if plan["key"] == "pumpkit_pro_annual")["amount"] == 25000
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["plan_key"] is None
    assert me["future_plan"]["amount"] == 20000
    assert me["future_plan"]["first_payment_at"] == added["ends_at"]
    assert me["future_plan"]["first_payment_at"] != old_result["first_payment_at"]
    assert (await authed_client.get(CHANGES + "/" + change["operation_id"])).json() == old_result


async def test_expired_access_keeps_account_linked_change_recovery_after_external_cancellation(
    authed_client,
    coupons,
    db,
    user,
    fake_billing,
    fixed_clock,
    monkeypatch,
):
    offer = await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    fake_billing.delay_plan_changes = True
    assert (await authed_client.post(CHANGES, json=request)).json()["status"] == "pending"
    state = (await fake_billing.list_subscriptions(customer_id=user.stripe_customer_id))[0]
    fake_billing.set_subscription(
        user.stripe_customer_id, replace(state, status="canceled", cancel_at=state.trial_end)
    )
    fixed_clock.advance(
        datetime.fromisoformat(offer["ends_at"].replace("Z", "+00:00"))
        - fixed_clock()
        + timedelta(seconds=1)
    )
    monkeypatch.setattr(settings, "COUPONS_ENABLED", False)
    assert (
        await _send(
            authed_client,
            fake_billing,
            "evt_expired_pending_change",
            "customer.subscription.deleted",
            {"customer": user.stripe_customer_id},
        )
    ).status_code == 200
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscribed"] is False
    assert me["pending_plan_change_id"] == request["operation_id"]
    assert (await authed_client.get("/api/v1/onboarding")).json()["next_step"] == "paywall"
    assert (await authed_client.get(CHANGES + "/" + request["operation_id"])).json()[
        "status"
    ] == "pending"
    assert (
        await authed_client.post(
            "/api/v1/billing/checkout",
            json={
                "plan_key": "pumpkit_pro_monthly",
                "terms_version": TERMS_VERSION,
                "accepted_terms": True,
                "requested_immediate_start": True,
                "approved_specific_clauses": True,
            },
        )
    ).status_code == 409
    fake_billing.complete_pending_plan_change(next(iter(fake_billing.pending_plan_changes)))
    assert (await authed_client.get(CHANGES + "/" + request["operation_id"])).json()[
        "status"
    ] == "pending"
    assert (await authed_client.get("/api/v1/billing/me")).json()[
        "pending_plan_change_id"
    ] == request["operation_id"]


@pytest.mark.parametrize("legacy", [False, True])
async def test_recovery_keeps_the_original_provider_anchor_policy(
    authed_client, coupons, db, user, fake_billing, fixed_clock, monkeypatch, legacy
):
    offer = await deferred(authed_client, coupons, db, user, fake_billing, fixed_clock)
    request = await proposed_change(authed_client)
    fake_billing.delay_plan_changes = True
    assert (await authed_client.post(CHANGES, json=request)).json()["status"] == "pending"
    if legacy:
        operation = await db.scalar(select(PlanChange))
        assert operation is not None
        operation.offer = {k: v for k, v in operation.offer.items() if k != "preserve_payment_date"}
        await db.commit()
    fake_billing.delay_plan_changes = False
    change = fake_billing.change_plan

    async def check_policy(*, first_payment_at=None, **kwargs):
        expected = (
            None if legacy else datetime.fromisoformat(offer["ends_at"].replace("Z", "+00:00"))
        )
        assert first_payment_at == expected
        await change(**kwargs)

    monkeypatch.setattr(fake_billing, "change_plan", check_policy)
    result = await authed_client.get(CHANGES + "/" + request["operation_id"])
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed"
