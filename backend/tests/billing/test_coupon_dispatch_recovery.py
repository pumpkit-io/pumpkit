from dataclasses import replace
from datetime import datetime, timedelta
from io import StringIO

import pytest
from sqlalchemy import select

from alembic import command
from pumpkit.account_deletion import run_cli as delete_cli
from pumpkit.billing.allowance import months_after
from pumpkit.billing.coupons import run_cli
from pumpkit.billing.models import CouponOperation
from pumpkit.core.config import settings
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_monthly_coupons import monthly
from tests.billing.test_top_ups import _send
from tests.migrations import migrate


@pytest.mark.parametrize("coverage", ["month", "year", "trial"])
@pytest.mark.parametrize("process_stop", [False, True])
async def test_late_original_deferral_survives_rejected_retry_and_restart(
    authed_client,
    coupons,
    db,
    user,
    fake_billing,
    fixed_clock,
    db_session_maker,
    file_storage,
    new_browser,
    sign_in_by_magic_link,
    monkeypatch,
    coverage,
    process_stop,
):
    state = await monthly(db, user, fake_billing, fixed_clock)
    if coverage == "year":
        assert state.current_period_start is not None
        state = replace(
            state, interval="year", current_period_end=months_after(state.current_period_start, 12)
        )
    elif coverage == "trial":
        state = replace(
            state,
            status="trialing",
            paid_current_period=False,
            trial_start=state.current_period_start,
            trial_end=state.current_period_end,
            billing_cycle_anchor=state.current_period_end,
        )
    fake_billing.set_subscription("cus_monthly", state)
    code = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    fake_billing.delay_deferrals = True
    dispatch = fake_billing.defer_renewal

    async def stop_after_dispatch(**kwargs):
        try:
            await dispatch(**kwargs)
        except Exception:
            raise RuntimeError("Process stopped after dispatch")

    if process_stop:
        monkeypatch.setattr(fake_billing, "defer_renewal", stop_after_dispatch)
    result = await authed_client.post(REDEEM, json=confirmation(offer))
    assert result.status_code == (500 if process_stop else 200)
    monkeypatch.setattr(fake_billing, "defer_renewal", dispatch)
    async with db_session_maker() as fresh:
        saved = await fresh.scalar(select(CouponOperation))
        assert saved.attempted_at is not None
        assert saved.dispatch_count == 1
    fake_billing.fail_on.add("refuse_deferral")
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "pending"
    other = new_browser()
    signed = await sign_in_by_magic_link(other, "capacity-competitor@example.com")
    other.headers["Authorization"] = "Bearer " + signed.access_token
    assert (await other.post(PREVIEW, json={"code": code["code"]})).status_code == 409
    assert (await authed_client.post("/api/v1/billing/cancel-renewal")).status_code == 409
    assert (
        await delete_cli(
            ["--user-id", user.id],
            sessions=db_session_maker,
            gateway=fake_billing,
            storage=file_storage,
            stdout=StringIO(),
            stderr=StringIO(),
        )
        == 1
    )
    before = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert before["generations"]["limit"] == (125 if coverage == "trial" else 500)
    monkeypatch.setattr(settings, "COUPONS_ENABLED", False)
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 900)
    fake_billing.fail_on.clear()
    fake_billing.complete_pending_deferral(next(iter(fake_billing.pending_deferrals)))
    await _send(
        authed_client,
        fake_billing,
        "evt_late_coupon",
        "customer.subscription.updated",
        {"customer": "cus_monthly"},
    )
    result = await authed_client.get(REDEEM + "/redeem-test-0001")
    assert result.json()["status"] == "completed"
    assert result.json()["ends_at"] == offer["ends_at"]
    assert (await authed_client.get("/api/v1/usage")).json()["allowance"] == before
    assert (await coupons(code["id"], command="inspect"))["redeemed_count"] == 1
    assert len(fake_billing.deferrals) == 1
    fixed_clock.advance(
        datetime.fromisoformat(offer["starts_at"].replace("Z", "+00:00")) - fixed_clock()
    )
    free_usage = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    assert free_usage["generations"]["limit"] == 500
    assert free_usage["trial"] is False
    assert free_usage["resets_at"] == offer["ends_at"]


async def test_recovery_observes_late_effect_beyond_retention_without_replaying(
    authed_client,
    coupons,
    db,
    user,
    fake_billing,
    fixed_clock,
    db_session_maker,
    monkeypatch,
):
    await monthly(db, user, fake_billing, fixed_clock)
    code = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    fake_billing.delay_deferrals = True
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "pending"
    fixed_clock.advance(timedelta(hours=24))
    fake_billing.delay_deferrals = False
    monkeypatch.setattr(settings, "COUPONS_ENABLED", False)
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "pending"
    assert fake_billing.deferrals == []
    fake_billing.complete_pending_deferral(next(iter(fake_billing.pending_deferrals)))
    out = StringIO()
    assert (
        await run_cli(
            ["recover"],
            sessions=db_session_maker,
            config=settings,
            gateway=fake_billing,
            clock=fixed_clock,
            stdout=out,
            stderr=StringIO(),
        )
        == 0
    )
    assert "completed" in out.getvalue()
    assert len(fake_billing.deferrals) == 1


async def test_cancelled_old_state_does_not_resolve_a_dispatched_unknown_deferral(
    authed_client,
    coupons,
    db,
    user,
    fake_billing,
    fixed_clock,
):
    state = await monthly(db, user, fake_billing, fixed_clock)
    code = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    fake_billing.delay_deferrals = True
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "pending"
    fake_billing.set_subscription(
        "cus_monthly", replace(state, status="canceled", cancel_at=state.current_period_end)
    )
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "pending"
    assert (await coupons(code["id"], command="inspect"))["redeemed_count"] == 0
    assert (await authed_client.get("/api/v1/billing/me")).json()["pending_coupon_operation"]


async def test_retention_deadline_is_checked_after_slow_provider_reads(
    authed_client,
    coupons,
    db,
    user,
    fake_billing,
    fixed_clock,
    monkeypatch,
):
    await monthly(db, user, fake_billing, fixed_clock)
    code = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    fake_billing.fail_on.add("defer_renewal")
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "pending"
    fake_billing.fail_on.clear()
    fixed_clock.advance(timedelta(hours=22))
    read = fake_billing.has_unsettled_invoices

    async def slow_read(**kwargs):
        fixed_clock.advance(timedelta(hours=1))
        return await read(**kwargs)

    monkeypatch.setattr(fake_billing, "has_unsettled_invoices", slow_read)
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "pending"
    assert fake_billing.deferrals == []


@pytest.mark.parametrize("legacy_status", ["pending", "refused"])
async def test_migrated_zero_attempt_and_refused_records_need_conservative_recovery(
    authed_client,
    coupons,
    db,
    user,
    fake_billing,
    fixed_clock,
    db_engine,
    legacy_status,
):
    await monthly(db, user, fake_billing, fixed_clock)
    code = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    fake_billing.fail_on.add("refuse_deferral" if legacy_status == "refused" else "defer_renewal")
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == legacy_status
    saved = await db.scalar(select(CouponOperation))
    assert saved is not None
    saved.attempts = 0
    await db.commit()
    await migrate(db_engine, lambda config: command.stamp(config, "head"))
    await migrate(db_engine, lambda config: command.downgrade(config, "0052"))
    await migrate(db_engine, lambda config: command.upgrade(config, "head"))
    fake_billing.fail_on = {"refuse_deferral"}
    answer = await authed_client.get(REDEEM + "/redeem-test-0001")
    assert answer.json()["status"] == "pending"
    if legacy_status == "refused":
        assert "audit" in answer.json()["detail"]
    assert fake_billing.deferrals == []
    assert (await authed_client.get("/api/v1/billing/me")).json()["pending_coupon_operation"]


async def test_first_dispatch_known_unsent_after_target_expiry_releases_capacity(
    authed_client,
    coupons,
    db,
    user,
    fake_billing,
    fixed_clock,
    monkeypatch,
    new_browser,
    sign_in_by_magic_link,
):
    await monthly(db, user, fake_billing, fixed_clock)
    code = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    read = fake_billing.has_pending_checkout
    reads = 0

    async def slow_final_read(**kwargs):
        nonlocal reads
        reads += 1
        if reads == 2:
            fixed_clock.advance(timedelta(days=50))
        return await read(**kwargs)

    monkeypatch.setattr(fake_billing, "has_pending_checkout", slow_final_read)
    answer = await authed_client.post(REDEEM, json=confirmation(offer))
    assert answer.json()["status"] == "refused"
    assert fake_billing.deferrals == []
    other = new_browser()
    signed = await sign_in_by_magic_link(other, "unsent-competitor@example.com")
    other.headers["Authorization"] = "Bearer " + signed.access_token
    assert (await other.post(PREVIEW, json={"code": code["code"]})).status_code == 200
