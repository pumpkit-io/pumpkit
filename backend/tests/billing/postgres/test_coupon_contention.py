import asyncio
from datetime import timedelta
from io import StringIO

import pytest
from sqlalchemy import select, text

from pumpkit.account_deletion import run_cli
from pumpkit.auth.models import User
from pumpkit.billing.models import Coupon
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation

pytestmark = pytest.mark.postgres


async def browser_for(new_browser, sign_in, email):
    browser = new_browser()
    auth = await sign_in(browser, email)
    browser.headers["Authorization"] = "Bearer " + auth.access_token
    return browser


async def blocked_requests(engine, control, tasks, count):
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


async def test_waiting_confirmation_rechecks_deadline_and_preview_expiry(
    db_engine, db_session_maker, new_browser, sign_in_by_magic_link, coupons, fixed_clock
):
    browser = await browser_for(new_browser, sign_in_by_magic_link, "waiting@example.com")
    created = await coupons("--claim-deadline", (fixed_clock() + timedelta(minutes=1)).isoformat())
    offer = (await browser.post(PREVIEW, json={"code": created["code"]})).json()
    async with db_session_maker() as control:
        await control.scalar(select(Coupon).where(Coupon.id == created["id"]).with_for_update())
        task = asyncio.create_task(browser.post(REDEEM, json=confirmation(offer)))
        waiting = 0
        for _ in range(200):
            async with db_engine.connect() as connection:
                waiting = await connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE application_name = current_setting('application_name') AND wait_event_type = 'Lock'"
                    )
                )
            if waiting:
                break
            await asyncio.sleep(0.01)
        assert waiting
        fixed_clock.advance(timedelta(minutes=10))
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
