import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import select

from pumpkit.auth.models import User
from pumpkit.billing.models import Coupon
from tests.billing.postgres.test_coupon_contention import blocked_requests, browser_for
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_monthly_coupons import monthly

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
