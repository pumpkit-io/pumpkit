import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from io import StringIO

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text

from pumpkit.account_deletion import run_cli
from pumpkit.auth.models import User
from pumpkit.billing.models import Coupon
from pumpkit.core.config import settings
from pumpkit.scheduling.publisher import run_pass
from tests.billing.test_coupon_preview import KEYS
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_monthly_coupons import monthly
from tests.billing.test_top_ups import _send

pytestmark = pytest.mark.postgres


async def browser_for(new_browser, sign_in, email):
    browser = new_browser()
    auth = await sign_in(browser, email)
    browser.headers["Authorization"] = "Bearer " + auth.access_token
    return browser


async def wait_for_locks(engine, count):
    for _ in range(200):
        async with engine.connect() as connection:
            waiting = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name = current_setting('application_name') AND wait_event_type = 'Lock'"
                )
            )
        if waiting >= count:
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("Requests did not contend on independent PostgreSQL connections")


async def blocked_requests(engine, control, tasks, count):
    await wait_for_locks(engine, count)
    await control.commit()
    return await asyncio.wait_for(asyncio.gather(*tasks), 10)


@pytest.mark.parametrize("same_identity", [False, True])
async def test_independent_requests_cannot_duplicate_identity_or_take_last_slot(
    db_engine,
    db_session_maker,
    new_browser,
    sign_in_by_magic_link,
    coupons,
    fake_billing,
    same_identity,
):
    first = await browser_for(new_browser, sign_in_by_magic_link, "first@example.com")
    second = await browser_for(
        new_browser,
        sign_in_by_magic_link,
        "first@example.com" if same_identity else "second@example.com",
    )
    created = await coupons("--max-redemptions", "5" if same_identity else "1")
    offers = [
        (await browser.post(PREVIEW, json={"code": created["code"]})).json()
        for browser in (first, second)
    ]
    async with db_session_maker() as control:
        await control.scalar(select(Coupon).where(Coupon.id == created["id"]).with_for_update())
        tasks = [
            asyncio.create_task(
                browser.post(REDEEM, json=confirmation(offer, f"concurrent-operation-{index}"))
            )
            for index, (browser, offer) in enumerate(zip((first, second), offers))
        ]
        outcomes = await blocked_requests(db_engine, control, tasks, 2)
    assert sorted(response.status_code for response in outcomes) == [200, 409]
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 1
    assert sum(
        [
            (await browser.get("/api/v1/billing/me")).json()["subscribed"]
            for browser in (first, second)
        ]
    ) == (2 if same_identity else 1)
    assert fake_billing.checkouts == []


@pytest.mark.parametrize("boundary", ["deadline", "preview"])
async def test_waiting_confirmation_rechecks_deadline_and_preview_expiry(
    db_engine, db_session_maker, new_browser, sign_in_by_magic_link, coupons, fixed_clock, boundary
):
    browser = await browser_for(new_browser, sign_in_by_magic_link, "waiting@example.com")
    created = await coupons(
        *(
            ["--claim-deadline", (fixed_clock() + timedelta(minutes=1)).isoformat()]
            if boundary == "deadline"
            else []
        )
    )
    offer = (await browser.post(PREVIEW, json={"code": created["code"]})).json()
    async with db_session_maker() as control:
        await control.scalar(select(Coupon).where(Coupon.id == created["id"]).with_for_update())
        task = asyncio.create_task(browser.post(REDEEM, json=confirmation(offer)))
        await wait_for_locks(db_engine, 1)
        fixed_clock.advance(timedelta(minutes=2 if boundary == "deadline" else 10))
        await control.commit()
        response = await asyncio.wait_for(task, 10)
    assert response.status_code == 409
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0


async def test_same_operation_concurrent_confirmation_recovers_one_result(
    db_engine, db_session_maker, new_browser, sign_in_by_magic_link, coupons
):
    browser = await browser_for(new_browser, sign_in_by_magic_link, "replay@example.com")
    created = await coupons()
    offer = (await browser.post(PREVIEW, json={"code": created["code"]})).json()
    async with db_session_maker() as control:
        await control.scalar(select(Coupon).where(Coupon.id == created["id"]).with_for_update())
        tasks = [
            asyncio.create_task(browser.post(REDEEM, json=confirmation(offer))) for _ in range(2)
        ]
        results = await blocked_requests(db_engine, control, tasks, 2)
    assert [response.status_code for response in results] == [200, 200]
    assert results[0].json() == results[1].json()
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 1


async def test_disable_contends_with_claim_without_revoking_a_committed_benefit(
    db_engine, db_session_maker, new_browser, sign_in_by_magic_link, coupons
):
    browser = await browser_for(new_browser, sign_in_by_magic_link, "disabled@example.com")
    created = await coupons()
    offer = (await browser.post(PREVIEW, json={"code": created["code"]})).json()
    async with db_session_maker() as control:
        await control.scalar(select(Coupon).where(Coupon.id == created["id"]).with_for_update())
        tasks = [
            asyncio.create_task(browser.post(REDEEM, json=confirmation(offer))),
            asyncio.create_task(coupons(created["id"], command="disable")),
        ]
        result, _ = await blocked_requests(db_engine, control, tasks, 2)
    assert result.status_code in [200, 409]
    me = (await browser.get("/api/v1/billing/me")).json()
    assert me["subscribed"] == (result.status_code == 200)
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == int(
        result.status_code == 200
    )


async def test_deletion_and_claim_serialize_without_orphaned_grant(
    db_engine,
    db_session_maker,
    new_browser,
    sign_in_by_magic_link,
    coupons,
    fake_billing,
    file_storage,
):

    browser = await browser_for(new_browser, sign_in_by_magic_link, "deleted@example.com")
    created = await coupons("--max-redemptions", "2")
    offer = (await browser.post(PREVIEW, json={"code": created["code"]})).json()
    async with db_session_maker() as control:
        user = await control.scalar(
            select(User).where(User.email == "deleted@example.com").with_for_update()
        )
        user_id = user.id
        tasks = [
            asyncio.create_task(browser.post(REDEEM, json=confirmation(offer))),
            asyncio.create_task(
                run_cli(
                    ["--user-id", user_id],
                    sessions=db_session_maker,
                    gateway=fake_billing,
                    storage=file_storage,
                    stdout=StringIO(),
                    stderr=StringIO(),
                )
            ),
        ]
        result, status = await blocked_requests(db_engine, control, tasks, 2)
    assert status == 0
    assert result.status_code in [200, 403]
    assert (await browser.get("/api/v1/billing/me")).status_code == 401
    recreated = await browser_for(new_browser, sign_in_by_magic_link, "deleted@example.com")
    retry = await recreated.post(PREVIEW, json={"code": created["code"]})
    assert retry.status_code == (409 if result.status_code == 200 else 200)


async def test_rotating_active_key_between_same_email_requests_cannot_create_another_claim(
    new_browser, sign_in_by_magic_link, coupons, monkeypatch
):
    browser = await browser_for(new_browser, sign_in_by_magic_link, "rotation@example.com")
    created = await coupons("--max-redemptions", "2")
    offer = (await browser.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await browser.post(REDEEM, json=confirmation(offer))).status_code == 200
    ring = json.loads(KEYS)
    ring["keys"]["v2"] = "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE="
    ring["active"] = "v2"
    monkeypatch.setattr(settings, "COUPON_IDENTITY_KEYS", SecretStr(json.dumps(ring)))
    second = await browser_for(new_browser, sign_in_by_magic_link, "rotation@example.com")
    assert (
        await second.post(REDEEM, json=confirmation(offer, "rotated-second-operation"))
    ).status_code == 409
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 1


async def test_deletion_checks_a_publisher_claim_committed_while_it_waited_for_the_user(
    db_engine,
    db_session_maker,
    new_browser,
    sign_in_by_magic_link,
    coupons,
    fixed_clock,
    user,
    post_with,
    connect_x,
    fake_billing,
    fake_x_publisher,
    file_storage,
):
    fixed_clock.advance(timedelta(seconds=-30))
    browser = await browser_for(new_browser, sign_in_by_magic_link, user.email)
    created = await coupons()
    offer = (await browser.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await browser.post(REDEEM, json=confirmation(offer))).status_code == 200
    await connect_x()
    post_id = await post_with("Publish claimed while deletion waits for the User")
    at = fixed_clock() + timedelta(minutes=1)
    assert (
        await browser.post(
            "/api/v1/scheduled-posts", json={"post_id": post_id, "publish_at": at.isoformat()}
        )
    ).status_code == 201
    fixed_clock.advance(timedelta(minutes=1))
    error = StringIO()
    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == user.id).with_for_update())
        deletion = asyncio.create_task(
            run_cli(
                ["--user-id", user.id],
                sessions=db_session_maker,
                gateway=fake_billing,
                storage=file_storage,
                stdout=StringIO(),
                stderr=error,
            )
        )
        await wait_for_locks(db_engine, 1)
        publishing = asyncio.create_task(
            run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
        )
        status, _ = await blocked_requests(db_engine, control, [deletion, publishing], 2)
    assert status == 1
    assert "publishing" in error.getvalue()
    post = (await browser.get(f"/api/v1/posts/{post_id}")).json()
    assert post["scheduled_post"]["state"] == "published"
    assert post["scheduled_post"]["x_post_url"] == "https://x.com/i/web/status/1890000000000000001"


async def test_concurrent_distinct_appends_require_a_fresh_offer_without_lost_months(
    db_engine, db_session_maker, new_browser, sign_in_by_magic_link, coupons, fixed_clock
):
    browser = await browser_for(new_browser, sign_in_by_magic_link, "appending@example.com")
    initial = await coupons("--months", "1")
    offer = (await browser.post(PREVIEW, json={"code": initial["code"]})).json()
    assert (await browser.post(REDEEM, json=confirmation(offer))).status_code == 200
    codes = [await coupons("--months", "1") for _ in range(2)]
    offers = [(await browser.post(PREVIEW, json={"code": code["code"]})).json() for code in codes]
    async with db_session_maker() as control:
        await control.scalar(select(Coupon).where(Coupon.id == codes[0]["id"]).with_for_update())
        first = asyncio.create_task(
            browser.post(REDEEM, json=confirmation(offers[0], "append-operation-0"))
        )
        await wait_for_locks(db_engine, 1)
        second = asyncio.create_task(
            browser.post(REDEEM, json=confirmation(offers[1], "append-operation-1"))
        )
        outcomes = await blocked_requests(db_engine, control, [first, second], 2)
    assert [response.status_code for response in outcomes] == [200, 409]
    assert (await coupons(codes[1]["id"], command="inspect"))["redeemed_count"] == 0
    fresh = (await browser.post(PREVIEW, json={"code": codes[1]["code"]})).json()
    assert fresh["starts_at"] == outcomes[0].json()["ends_at"]
    result = await browser.post(REDEEM, json=confirmation(fresh, "append-operation-1"))
    assert result.status_code == 200
    assert (await browser.get("/api/v1/billing/me")).json()["free_access"]["months"] == 3
    assert (await coupons(codes[0]["id"], command="inspect"))["redeemed_count"] == 1
    assert (await coupons(codes[1]["id"], command="inspect"))["redeemed_count"] == 1
    assert (
        await browser.post(REDEEM, json=confirmation(fresh, "append-operation-1"))
    ).json() == result.json()


async def test_cancelled_redemption_replay_and_provider_nudge_share_earned_coverage(
    authed_client, coupons, db, user, fake_billing, fixed_clock, db_engine, db_session_maker
):
    state = await monthly(db, user, fake_billing, fixed_clock)
    cancelled = replace(state, cancel_at=state.current_period_end)
    fake_billing.set_subscription("cus_monthly", cancelled)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == user.id).with_for_update())
        tasks = [
            asyncio.create_task(authed_client.post(REDEEM, json=confirmation(offer))),
            asyncio.create_task(authed_client.post(REDEEM, json=confirmation(offer))),
            asyncio.create_task(
                _send(
                    authed_client,
                    fake_billing,
                    "evt_cancel_contending",
                    "customer.subscription.updated",
                    {"customer": "cus_monthly"},
                )
            ),
        ]
        responses = await blocked_requests(db_engine, control, tasks, 3)
    assert [response.status_code for response in responses] == [200, 200, 200]
    assert responses[0].json() == responses[1].json()
    assert responses[0].json()["next_payment_at"] is None
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 1
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["subscription"]["paid_through"] == offer["starts_at"]
    assert me["free_access"]["months"] == 1
    assert fake_billing.deferrals == []
    assert (await fake_billing.list_subscriptions(customer_id="cus_monthly"))[0] == cancelled
