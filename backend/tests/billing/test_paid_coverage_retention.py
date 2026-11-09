from dataclasses import replace
from datetime import datetime, timedelta

from sqlalchemy import select

from pumpkit.billing.allowance import paid_period
from pumpkit.billing.models import Subscription
from pumpkit.core.time import as_utc
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_monthly_coupons import monthly
from tests.billing.test_top_ups import _send


async def saved_paid_coverage(sessions, user_id):
    async with sessions() as db:
        return (
            await db.execute(
                select(
                    Subscription.paid_start,
                    Subscription.paid_end,
                    Subscription.paid_anchor,
                    Subscription.paid_allowance,
                ).where(Subscription.user_id == user_id)
            )
        ).one()


async def test_purge_minimizes_saved_paid_fields_and_preserves_provider_usage_and_new_claims(
    authed_client, coupons, db, user, fake_billing, fixed_clock, db_session_maker
):
    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1", "--max-redemptions", "2")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "completed"
    snapshot = await saved_paid_coverage(db_session_maker, user.id)
    assert all(value is not None for value in snapshot)
    target = datetime.fromisoformat(offer["ends_at"].replace("Z", "+00:00"))
    fixed_clock.advance(target + timedelta(days=90) - timedelta(seconds=1) - fixed_clock())
    deferred = (await fake_billing.list_subscriptions(customer_id="cus_monthly"))[0]
    period = paid_period(target, fixed_clock())
    fake_billing.set_subscription(
        "cus_monthly",
        replace(
            deferred,
            status="active",
            current_period_start=period.start,
            current_period_end=period.end,
            paid_current_period=True,
        ),
    )
    await _send(
        authed_client,
        fake_billing,
        "evt_resumed_paid",
        "customer.subscription.updated",
        {"customer": "cus_monthly"},
    )
    before = (await authed_client.get("/api/v1/billing/me")).json()
    usage = (await authed_client.get("/api/v1/usage")).json()
    await coupons(command="purge")
    assert await saved_paid_coverage(db_session_maker, user.id) == snapshot
    fixed_clock.advance(timedelta(seconds=1))
    await coupons(command="purge")
    assert await saved_paid_coverage(db_session_maker, user.id) == (None, None, None, None)
    assert (await authed_client.get("/api/v1/billing/me")).json() == before
    assert (await authed_client.get("/api/v1/usage")).json() == usage
    assert (await authed_client.post(PREVIEW, json={"code": created["code"]})).status_code == 409
    another = await coupons("--months", "1")
    next_offer = (await authed_client.post(PREVIEW, json={"code": another["code"]})).json()
    assert (
        await authed_client.post(REDEEM, json=confirmation(next_offer, "after-snapshot-purge"))
    ).json()["status"] == "completed"
    renewed = await saved_paid_coverage(db_session_maker, user.id)
    assert as_utc(renewed[0]) == period.start
    assert as_utc(renewed[1]) == period.end
    assert (await authed_client.get("/api/v1/usage")).json() == usage


async def test_late_resolution_extends_snapshot_retention_without_extending_benefit(
    authed_client, coupons, db, user, fake_billing, fixed_clock, db_session_maker
):
    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    fake_billing.fail_on.add("after_defer_renewal")
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "pending"
    snapshot = await saved_paid_coverage(db_session_maker, user.id)
    fixed_clock.advance(timedelta(days=200))
    await coupons(command="purge")
    assert await saved_paid_coverage(db_session_maker, user.id) == snapshot
    fake_billing.fail_on.clear()
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "completed"
    await coupons(command="purge")
    assert await saved_paid_coverage(db_session_maker, user.id) == snapshot
    fixed_clock.advance(timedelta(days=90) - timedelta(seconds=1))
    await coupons(command="purge")
    assert await saved_paid_coverage(db_session_maker, user.id) == snapshot
    fixed_clock.advance(timedelta(seconds=1))
    await coupons(command="purge")
    assert await saved_paid_coverage(db_session_maker, user.id) == (None, None, None, None)
    assert len(fake_billing.deferrals) == 1


async def test_purge_keeps_saved_paid_fields_while_free_benefit_is_current_or_queued(
    authed_client, coupons, db, user, fake_billing, fixed_clock, db_session_maker
):
    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "12")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "completed"
    snapshot = await saved_paid_coverage(db_session_maker, user.id)
    await coupons(command="purge")
    assert await saved_paid_coverage(db_session_maker, user.id) == snapshot
    fixed_clock.advance(timedelta(days=150))
    before = (await authed_client.get("/api/v1/usage")).json()
    await coupons(command="purge")
    assert await saved_paid_coverage(db_session_maker, user.id) == snapshot
    assert (await authed_client.get("/api/v1/usage")).json() == before


async def test_refused_offer_does_not_keep_saved_paid_fields_until_its_ungranted_end(
    authed_client, coupons, db, user, fake_billing, fixed_clock, db_session_maker
):
    state = await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "12")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    fake_billing.fail_on.add("refuse_deferral")
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "refused"
    assert state.current_period_end is not None
    fixed_clock.advance(state.current_period_end + timedelta(days=90) - fixed_clock())
    before = (await authed_client.get("/api/v1/usage")).json()
    await coupons(command="purge")
    assert await saved_paid_coverage(db_session_maker, user.id) == (None, None, None, None)
    assert (await authed_client.get("/api/v1/usage")).json() == before
