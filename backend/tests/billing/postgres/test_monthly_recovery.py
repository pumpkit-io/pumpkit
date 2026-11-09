import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select

from pumpkit.auth.models import User
from pumpkit.billing.allowance import paid_period
from pumpkit.billing.models import Coupon
from pumpkit.core.time import as_utc
from tests.billing.postgres.test_coupon_contention import (
    blocked_requests,
    browser_for,
    wait_for_locks,
)
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_monthly_coupons import monthly
from tests.billing.test_paid_coverage_retention import saved_paid_coverage

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("same_identity", [False, True])
async def test_last_reservation_and_duplicate_recovery_use_independent_database_locks(
    db_engine,
    db_session_maker,
    db,
    new_browser,
    sign_in_by_magic_link,
    coupons,
    fake_billing,
    fixed_clock,
    same_identity,
):
    first = await browser_for(new_browser, sign_in_by_magic_link, "monthly-first@example.com")
    second = await browser_for(
        new_browser,
        sign_in_by_magic_link,
        "monthly-first@example.com" if same_identity else "monthly-second@example.com",
    )
    user = await db.scalar(select(User).where(User.email == "monthly-first@example.com"))
    state = await monthly(db, user, fake_billing, fixed_clock)
    if not same_identity:
        user2 = await db.scalar(select(User).where(User.email == "monthly-second@example.com"))
        user2.stripe_customer_id = "cus_second"
        await db.commit()
        fake_billing.set_subscription("cus_second", replace(state, id="sub_second"))
    created = await coupons("--months", "1", "--max-redemptions", "5" if same_identity else "1")
    offers = [
        (await browser.post(PREVIEW, json={"code": created["code"]})).json()
        for browser in (first, second)
    ]
    fake_billing.fail_on.add("defer_renewal")
    async with db_session_maker() as control:
        await control.scalar(select(Coupon).where(Coupon.id == created["id"]).with_for_update())
        tasks = [
            asyncio.create_task(
                browser.post(REDEEM, json=confirmation(offer, f"monthly-contention-{i}"))
            )
            for i, (browser, offer) in enumerate(zip((first, second), offers))
        ]
        responses = await blocked_requests(db_engine, control, tasks, 1 if same_identity else 2)
    assert sorted(response.status_code for response in responses) == [200, 409]
    index = next(i for i, response in enumerate(responses) if response.status_code == 200)
    winner = (first, second)[index]
    operation_id = responses[index].json()["operation_id"]
    assert responses[index].json()["status"] == "pending"
    await coupons(created["id"], command="disable")
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0
    fake_billing.fail_on.clear()
    async with db_session_maker() as control:
        winner_user = await control.scalar(
            select(User)
            .where(
                User.email
                == (
                    "monthly-first@example.com"
                    if index == 0 or same_identity
                    else "monthly-second@example.com"
                )
            )
            .with_for_update()
        )
        assert winner_user is not None
        tasks = [asyncio.create_task(winner.get(REDEEM + "/" + operation_id)) for _ in range(2)]
        outcomes = await blocked_requests(db_engine, control, tasks, 2)
    assert [response.json()["status"] for response in outcomes] == ["completed", "completed"]
    assert len(fake_billing.deferrals) == 1
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 1


async def test_purge_skips_billing_user_lock_and_cannot_erase_a_new_paid_snapshot(
    db_engine, db_session_maker, db, authed_client, coupons, user, fake_billing, fixed_clock
):
    state = await monthly(db, user, fake_billing, fixed_clock)
    first = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": first["code"]})).json()
    fake_billing.fail_on.add("refuse_deferral")
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "refused"
    original = await saved_paid_coverage(db_session_maker, user.id)
    assert state.current_period_end is not None and state.billing_cycle_anchor is not None
    fixed_clock.advance(state.current_period_end + timedelta(days=91) - fixed_clock())
    period = paid_period(state.billing_cycle_anchor, fixed_clock())
    fake_billing.set_subscription(
        "cus_monthly",
        replace(state, current_period_start=period.start, current_period_end=period.end),
    )
    fake_billing.fail_on.clear()
    second = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": second["code"]})).json()
    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == user.id).with_for_update())
        claim = asyncio.create_task(
            authed_client.post(REDEEM, json=confirmation(offer, "new-paid-cycle-0001"))
        )
        try:
            await wait_for_locks(db_engine, 1)
            await asyncio.wait_for(coupons(command="purge"), 5)
            assert await saved_paid_coverage(db_session_maker, user.id) == original
            await control.commit()
            response = await asyncio.wait_for(claim, 10)
        finally:
            if not claim.done():
                claim.cancel()
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"
    refreshed = await saved_paid_coverage(db_session_maker, user.id)
    assert as_utc(refreshed[0]) == period.start
    assert as_utc(refreshed[1]) == period.end
    await coupons(command="purge")
    assert await saved_paid_coverage(db_session_maker, user.id) == refreshed
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["paid_through"] == period.end.isoformat().replace("+00:00", "Z")


@pytest.mark.parametrize("replay_error", ["deferral_in_progress", "refuse_deferral"])
async def test_independent_recovery_and_capacity_competition_preserve_delayed_deferral(
    db_engine,
    db_session_maker,
    db,
    authed_client,
    user,
    new_browser,
    sign_in_by_magic_link,
    coupons,
    fake_billing,
    fixed_clock,
    replay_error,
):
    await monthly(db, user, fake_billing, fixed_clock)
    competitor = await browser_for(
        new_browser, sign_in_by_magic_link, "deferral-competitor@example.com"
    )
    code = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    other_offer = (await competitor.post(PREVIEW, json={"code": code["code"]})).json()
    fake_billing.delay_deferrals = True
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "pending"
    fake_billing.fail_on.add(replay_error)
    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == user.id).with_for_update())
        tasks = [
            asyncio.create_task(authed_client.get(REDEEM + "/redeem-test-0001")) for _ in range(2)
        ]
        try:
            await wait_for_locks(db_engine, 2)
            competing = await competitor.post(
                REDEEM, json=confirmation(other_offer, "pg-other-claim-0001")
            )
            assert competing.status_code == 409
            await control.commit()
            results = await asyncio.wait_for(asyncio.gather(*tasks), 10)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
    assert all(result.json()["status"] == "pending" for result in results)
    assert fake_billing.deferrals == []
    fake_billing.fail_on.clear()
    fake_billing.complete_pending_deferral(next(iter(fake_billing.pending_deferrals)))
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "completed"
    assert len(fake_billing.deferrals) == 1
    assert (await coupons(code["id"], command="inspect"))["redeemed_count"] == 1


async def test_recovery_generation_handoff_prevents_stale_first_refusal_releasing_claim(
    db_engine,
    authed_client,
    coupons,
    user,
    db,
    fake_billing,
    fixed_clock,
    monkeypatch,
):
    await monthly(db, user, fake_billing, fixed_clock)
    code = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": code["code"]})).json()
    entered, release = asyncio.Event(), asyncio.Event()
    original_read = fake_billing.list_subscriptions
    reads = 0

    async def slow_confirmation_read(**kwargs):
        nonlocal reads
        reads += 1
        if reads == 3:
            entered.set()
            await asyncio.wait_for(release.wait(), 10)
        return await original_read(**kwargs)

    monkeypatch.setattr(fake_billing, "list_subscriptions", slow_confirmation_read)
    fake_billing.fail_on.add("refuse_deferral")
    confirming = asyncio.create_task(authed_client.post(REDEEM, json=confirmation(offer)))
    await asyncio.wait_for(entered.wait(), 10)
    recovering = asyncio.create_task(authed_client.get(REDEEM + "/redeem-test-0001"))
    try:
        await wait_for_locks(db_engine, 1)
    finally:
        release.set()
    results = await asyncio.wait_for(asyncio.gather(confirming, recovering), 10)
    assert all(
        result.status_code == 200 and result.json()["status"] == "pending" for result in results
    )
    fake_billing.fail_on.clear()
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "completed"
    assert len(fake_billing.deferrals) == 1
