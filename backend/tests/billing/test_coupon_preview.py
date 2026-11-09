import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import StringIO

import pytest
from pydantic import SecretStr

from pumpkit.billing.coupons import run_cli
from pumpkit.billing.gateway import Plan, SubscriptionState
from pumpkit.core.config import settings

PREVIEW = "/api/v1/billing/coupons/preview"
KEYS = '{"active":"v1","keys":{"v1":"MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="}}'


@pytest.fixture
def coupons(monkeypatch, db_session_maker, fake_billing, fixed_clock):
    monkeypatch.setattr(settings, "COUPONS_ENABLED", True)
    monkeypatch.setattr(settings, "COUPON_IDENTITY_KEYS", SecretStr(KEYS))
    fake_billing.plans = [
        Plan("pumpkit_pro_monthly", "price_monthly", "Pro", 2000, "eur", "month", 1)
    ]

    async def issue(*args, command="create"):
        arguments = ["create", "--months", "3", *args] if command == "create" else [command, *args]
        out, err = StringIO(), StringIO()
        status = await run_cli(
            arguments,
            sessions=db_session_maker,
            config=settings,
            gateway=fake_billing,
            clock=fixed_clock,
            stdout=out,
            stderr=err,
        )
        assert (status, err.getvalue()) == (0, "")
        return json.loads(out.getvalue())

    return issue


async def test_cli_code_previews_full_months_without_a_claim_or_provider_mutation(
    client, coupons, fake_billing, fixed_clock
):
    fixed_clock.advance(datetime(2028, 1, 31, 12, 0, tzinfo=timezone.utc) - fixed_clock())
    created = await coupons("--recipient", "Alice@Example.COM")

    first = await client.post(PREVIEW, json={"code": created["code"]})
    assert first.status_code == 200
    result = first.json()
    assert result["months"] == 3
    assert result["starts_at"] == "2028-01-31T12:00:00Z"
    assert result["ends_at"] == "2028-04-30T12:00:00Z"
    assert result["next_payment_at"] is None
    assert result["terms_version"] == "2026-11-08"
    assert result["allowance"] == {"generations": 500, "x_posts": 100, "link_x_posts": 10}
    assert result["revision"]
    again = await client.post(PREVIEW, json={"code": created["code"]})
    assert again.status_code == 200
    assert (await client.get("/api/v1/billing/me")).json()["subscribed"] is False
    assert fake_billing.checkouts == []


async def test_preview_availability_follows_default_off_and_no_plan_instances(
    client, coupons, monkeypatch
):
    created = await coupons()
    assert (await client.get("/api/v1/billing/plans")).json()["coupons_enabled"] is True
    monkeypatch.setattr(settings, "COUPONS_ENABLED", False)
    assert (await client.get("/api/v1/billing/plans")).json()["coupons_enabled"] is False
    refused = await client.post(PREVIEW, json={"code": created["code"]})
    assert refused.status_code == 422


@pytest.mark.parametrize("case", ["unknown", "disabled", "deadline", "recipient", "horizon"])
async def test_unavailable_codes_are_private_nonconsuming_refusals(
    client, coupons, fixed_clock, case, caplog
):
    args = {
        "deadline": ["--claim-deadline", "2026-10-10T12:01:00Z"],
        "recipient": ["--recipient", "someone@example.com"],
        "horizon": ["--months", "2147483647"],
    }.get(case, [])
    created = await coupons(*args)
    if case == "disabled":
        await coupons(created["id"], command="disable")
    if case == "deadline":
        fixed_clock.advance(timedelta(seconds=30))
    code = "unknown-code" if case == "unknown" else created["code"]
    response = await client.post(PREVIEW, json={"code": code})
    assert response.status_code == 409
    assert "someone@example.com" not in response.text
    assert code not in response.text
    assert code not in caplog.text
    assert (await client.get("/api/v1/billing/me")).json()["subscribed"] is False
    inspected = await coupons(created["id"], command="inspect")
    assert inspected["redeemed_count"] == 0


@pytest.mark.parametrize(
    "facts, explanation",
    [
        ({"status": "past_due"}, "payment"),
        ({"status": "incomplete"}, "payment"),
        ({"status": "canceled", "latest_invoice_status": "open"}, "payment"),
        ({"status": "active", "has_pending_update": True}, "pending"),
        ({"status": "active", "schedule_id": "sub_sched_test"}, "pending"),
        ({"status": "active"}, "not available yet"),
    ],
)
async def test_preview_uses_current_provider_eligibility_without_mutation(
    client, coupons, db, user, fake_billing, fixed_clock, facts, explanation
):
    created = await coupons()
    user.stripe_customer_id = "cus_preview"
    await db.commit()
    state = SubscriptionState(
        id="sub_preview",
        status="active",
        price_id="price_monthly",
        plan_key="pumpkit_pro_monthly",
        current_period_end=fixed_clock() + timedelta(days=20),
        created_at=fixed_clock(),
        **{key: value for key, value in facts.items() if key != "status"},
    )
    fake_billing.set_subscription("cus_preview", replace(state, status=facts["status"]))
    response = await client.post(PREVIEW, json={"code": created["code"]})
    assert response.status_code == 409
    assert explanation in response.json()["detail"]
    assert fake_billing.checkouts == []
    assert fake_billing.cancelled_subscriptions == []


async def test_old_customer_debt_is_refused_even_without_a_running_subscription(
    client, coupons, db, user, fake_billing
):
    created = await coupons()
    user.stripe_customer_id = "cus_older_debt"
    await db.commit()
    fake_billing.unsettled_invoice_customers.add("cus_older_debt")
    response = await client.post(PREVIEW, json={"code": created["code"]})
    assert response.status_code == 409
    assert "payment" in response.json()["detail"]


async def test_preview_rate_limits_repeated_code_guesses_per_user(client, coupons):
    await coupons()
    for _ in range(10):
        assert (await client.post(PREVIEW, json={"code": "guess"})).status_code == 409
    assert (await client.post(PREVIEW, json={"code": "guess"})).status_code == 429


async def test_preview_without_operator_details_has_no_terms_to_accept(
    client, coupons, no_operator_details
):
    created = await coupons()
    assert (await client.post(PREVIEW, json={"code": created["code"]})).json()[
        "terms_version"
    ] is None


async def test_preview_rejects_caller_supplied_recipient_or_benefit(client, coupons):
    created = await coupons()
    assert (
        await client.post(
            PREVIEW, json={"code": created["code"], "recipient": "alice@example.com", "months": 99}
        )
    ).status_code == 422


async def test_preview_refuses_incompatible_changed_offers(client, coupons, fake_billing):
    created = await coupons()
    fake_billing.plans = []
    assert (await client.post(PREVIEW, json={"code": created["code"]})).status_code == 409


async def test_preview_requires_authentication(new_browser, coupons):
    created = await coupons()
    browser = new_browser()
    assert (await browser.post(PREVIEW, json={"code": created["code"]})).status_code == 401


async def test_preview_refuses_suspended_recipients(authed_client, coupons, suspend_user, user):
    created = await coupons()
    await suspend_user(user.email)
    assert (await authed_client.post(PREVIEW, json={"code": created["code"]})).status_code == 401


@pytest.mark.parametrize(
    "anchor, months, expected_end, status",
    [
        ("2028-01-31T12:00:00+00:00", 1, "2028-02-29T12:00:00Z", 200),
        ("2028-01-31T12:00:00+00:00", 2, "2028-03-31T12:00:00Z", 200),
        ("2027-01-31T12:00:00+00:00", 1, "2027-02-28T12:00:00Z", 200),
        ("2029-03-01T12:00:00+00:00", 24, "2031-03-01T12:00:00Z", 200),
        ("2027-03-01T12:00:00+00:00", 24, None, 409),
    ],
)
async def test_preview_calendar_boundaries_and_exact_horizon(
    client, coupons, fixed_clock, anchor, months, expected_end, status
):
    fixed_clock.advance(datetime.fromisoformat(anchor) - fixed_clock())
    created = await coupons("--months", str(months))
    response = await client.post(PREVIEW, json={"code": created["code"]})
    assert response.status_code == status
    if expected_end:
        assert response.json()["ends_at"] == expected_end
