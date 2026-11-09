from dataclasses import replace
from datetime import timedelta
from io import StringIO

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from pumpkit.account_deletion import run_cli as delete_cli
from pumpkit.billing.gateway import BillingProviderError
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_monthly_coupons import monthly


@pytest.mark.parametrize("settlement", ["invoice", "checkout"])
@pytest.mark.parametrize("hours", [1, 24])
async def test_new_payment_obligation_before_first_deferral_does_not_strand_the_coupon(
    authed_client,
    coupons,
    db,
    user,
    fake_billing,
    fixed_clock,
    monkeypatch,
    new_browser,
    sign_in_by_magic_link,
    db_session_maker,
    file_storage,
    settlement,
    hours,
):
    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    method = "has_unsettled_invoices" if settlement == "invoice" else "has_pending_checkout"
    original_read = getattr(fake_billing, method)
    reads = 0
    writes = []
    original_write = fake_billing.defer_renewal

    async def new_obligation(**kwargs):
        nonlocal reads
        reads += 1
        return reads == 2 or await original_read(**kwargs)

    async def write(**kwargs):
        writes.append(kwargs)
        await original_write(**kwargs)

    monkeypatch.setattr(fake_billing, method, new_obligation)
    monkeypatch.setattr(fake_billing, "defer_renewal", write)
    confirmed = await authed_client.post(REDEEM, json=confirmation(offer))
    assert confirmed.status_code == 200, confirmed.text
    assert reads == 2
    assert writes == []
    fixed_clock.advance(timedelta(hours=hours))
    recovered = await authed_client.get(REDEEM + "/redeem-test-0001")
    assert recovered.json()["status"] == "refused", recovered.text
    assert confirmed.json()["status"] == "refused"
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["pending_coupon_operation"] is False
    assert me["free_access"] is None
    assert me["subscribed"] is True
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0
    other = new_browser()
    signed = await sign_in_by_magic_link(other, "unsent-capacity@example.com")
    other.headers["Authorization"] = "Bearer " + signed.access_token
    assert (await other.post(PREVIEW, json={"code": created["code"]})).status_code == 200
    assert (await authed_client.post("/api/v1/billing/cancel-renewal")).status_code == 200
    await fake_billing.cancel_subscription(subscription_id="sub_monthly")
    assert (
        await delete_cli(
            ["--user-id", user.id],
            sessions=db_session_maker,
            gateway=fake_billing,
            storage=file_storage,
            stdout=StringIO(),
            stderr=StringIO(),
        )
        == 0
    )
    assert writes == []


@pytest.mark.parametrize("settlement", ["invoice", "checkout"])
@pytest.mark.parametrize("hours", [1, 24])
async def test_later_payment_obligation_never_releases_an_earlier_unknown_deferral(
    authed_client,
    coupons,
    db,
    user,
    fake_billing,
    fixed_clock,
    monkeypatch,
    new_browser,
    sign_in_by_magic_link,
    db_session_maker,
    file_storage,
    settlement,
    hours,
):
    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    writes = []
    original_write = fake_billing.defer_renewal

    async def write(**kwargs):
        writes.append(kwargs)
        await original_write(**kwargs)

    monkeypatch.setattr(fake_billing, "defer_renewal", write)
    fake_billing.delay_deferrals = True
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
        "status"
    ] == "pending"
    usage = (await authed_client.get("/api/v1/usage")).json()["allowance"]
    method = "has_unsettled_invoices" if settlement == "invoice" else "has_pending_checkout"
    original_read = getattr(fake_billing, method)
    blocked = True

    async def new_obligation(**kwargs):
        return blocked or await original_read(**kwargs)

    monkeypatch.setattr(fake_billing, method, new_obligation)
    fixed_clock.advance(timedelta(hours=hours))
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "pending"
    assert len(writes) == 1
    blocked = False
    fixed_clock.advance(timedelta(hours=24 if hours == 1 else 1))
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "pending"
    assert len(writes) == 1
    me = (await authed_client.get("/api/v1/billing/me")).json()
    assert me["pending_coupon_operation"] is True
    assert me["free_access"] is None
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
    other = new_browser()
    signed = await sign_in_by_magic_link(other, "unknown-capacity@example.com")
    other.headers["Authorization"] = "Bearer " + signed.access_token
    assert (await other.post(PREVIEW, json={"code": created["code"]})).status_code == 409
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0
    fake_billing.complete_pending_deferral(next(iter(fake_billing.pending_deferrals)))
    result = await authed_client.get(REDEEM + "/redeem-test-0001")
    assert result.json()["status"] == "completed"
    assert result.json()["ends_at"] == offer["ends_at"]
    assert (await authed_client.get("/api/v1/usage")).json()["allowance"] == usage
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 1
    assert len(writes) == 1


@pytest.mark.parametrize("change", ["missing", "incompatible", "read_error"])
@pytest.mark.parametrize("earlier_unknown", [False, True])
async def test_final_provider_read_without_a_write_only_releases_a_proven_first_dispatch(
    authed_client,
    coupons,
    db,
    user,
    fake_billing,
    fixed_clock,
    monkeypatch,
    change,
    earlier_unknown,
):
    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    if earlier_unknown:
        fake_billing.delay_deferrals = True
        assert (await authed_client.post(REDEEM, json=confirmation(offer))).json()[
            "status"
        ] == "pending"
    original_read = fake_billing.list_subscriptions
    reads = 0

    async def final_read(**kwargs):
        nonlocal reads
        reads += 1
        if reads == (2 if earlier_unknown else 4):
            if change == "read_error":
                raise BillingProviderError("Provider read failed before any new write")
            if change == "missing":
                return []
            return [replace(state, paused=True) for state in await original_read(**kwargs)]
        return await original_read(**kwargs)

    monkeypatch.setattr(fake_billing, "list_subscriptions", final_read)
    result = (
        await authed_client.get(REDEEM + "/redeem-test-0001")
        if earlier_unknown
        else await authed_client.post(REDEEM, json=confirmation(offer))
    )
    assert result.status_code == 200
    assert result.json()["status"] == ("pending" if earlier_unknown else "refused")
    assert (await authed_client.get("/api/v1/billing/me")).json()[
        "pending_coupon_operation"
    ] is earlier_unknown
    assert fake_billing.deferrals == []


@pytest.mark.parametrize("settlement", ["invoice", "checkout"])
async def test_lost_unsent_refusal_commit_keeps_recovery_guarded_until_a_confirmed_retry(
    authed_client,
    coupons,
    db,
    user,
    fake_billing,
    fixed_clock,
    monkeypatch,
    db_session_maker,
    file_storage,
    settlement,
):
    await monthly(db, user, fake_billing, fixed_clock)
    created = await coupons("--months", "1")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    method = "has_unsettled_invoices" if settlement == "invoice" else "has_pending_checkout"
    original_read = getattr(fake_billing, method)
    reads = 0
    blocked = True
    armed = False
    failed = False
    writes = []
    original_write = fake_billing.defer_renewal

    async def new_obligation(**kwargs):
        nonlocal reads, armed
        reads += 1
        if reads >= 2 and blocked:
            armed = True
            return True
        return await original_read(**kwargs)

    async def write(**kwargs):
        writes.append(kwargs)
        await original_write(**kwargs)

    def lose_commit(session):
        nonlocal failed
        if armed and not failed:
            failed = True
            raise RuntimeError("Process lost its no-write refusal commit")

    monkeypatch.setattr(fake_billing, method, new_obligation)
    monkeypatch.setattr(fake_billing, "defer_renewal", write)
    event.listen(Session, "before_commit", lose_commit)
    try:
        assert (await authed_client.post(REDEEM, json=confirmation(offer))).status_code == 500
    finally:
        event.remove(Session, "before_commit", lose_commit)
    assert failed
    assert writes == []
    assert (await authed_client.get(REDEEM + "/redeem-test-0001")).json()["status"] == "pending"
    assert (await authed_client.get("/api/v1/billing/me")).json()[
        "pending_coupon_operation"
    ] is True
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
    blocked = False
    fixed_clock.advance(timedelta(hours=1))
    result = await authed_client.get(REDEEM + "/redeem-test-0001")
    assert result.json()["status"] == "completed"
    assert result.json()["ends_at"] == offer["ends_at"]
    assert len(writes) == 1
