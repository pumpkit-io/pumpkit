"""Opt-in proof of restricted hosted actions and current-state application reconciliation."""

import hashlib
import hmac
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from pumpkit.billing.gateway import BillingProviderError, StripeBillingGateway, get_billing_gateway
from pumpkit.core.config import settings
from pumpkit.main import app
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_stripe_managed_payments_live import (
    KEY,
    advance,
    at,
    complete_checkout,
    subscription_facts,
)
from tests.billing.test_stripe_managed_payments_live import (
    provider as provider,
)
from tests.billing.test_stripe_managed_payments_live import (
    record as record,
)

pytestmark = pytest.mark.skipif(not KEY, reason="requires explicit Stripe test-mode credential")
BROWSER = Path(__file__).resolve().parents[3] / "e2e" / "stripe-payment-method.mjs"


class LostDeferralResponseGateway(StripeBillingGateway):
    calls = 0

    async def defer_renewal(
        self, *, subscription_id: str, target: datetime, operation_id: str
    ) -> None:
        self.calls += 1
        await super().defer_renewal(
            subscription_id=subscription_id, target=target, operation_id=operation_id
        )
        if self.calls == 1:
            raise BillingProviderError("Synthetic lost response after the provider deferral")


def portal_browser(ledger: Path, action: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["node", str(BROWSER), str(ledger), action],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, "Hosted action failed; inspect private browser evidence"
    return json.loads(completed.stdout) if completed.stdout.strip() else {}


def reach_payment_date(client, clock: str, target: int, interval: str) -> None:
    # Test clocks cap each move at two billing intervals, even during a deferral.
    step = (45 if interval == "month" else 540) * 86400
    current = client.v1.test_helpers.test_clocks.retrieve(clock).frozen_time
    while current < target:
        current = min(target, current + step)
        advance(client, clock, current)


async def deliver_subscription_nudge(client, customer: str, subscription: str) -> None:
    payload = json.dumps(
        {
            "id": f"evt_558_{uuid4().hex}",
            "object": "event",
            "type": "customer.subscription.updated",
            "api_version": "2026-08-26.dahlia",
            "livemode": False,
            "data": {"object": {"id": subscription, "customer": customer, "status": "canceled"}},
        }
    ).encode()
    timestamp = int(time.time())
    digest = hmac.new(b"whsec_558", str(timestamp).encode() + b"." + payload, hashlib.sha256)
    for _ in range(2):
        response = await client.post(
            "/api/v1/stripe/webhook",
            content=payload,
            headers={"stripe-signature": f"t={timestamp},v1={digest.hexdigest()}"},
        )
        assert response.status_code == 200, response.text


@pytest.fixture
def restricted_configuration(provider, monkeypatch):
    client, _, _ = provider
    configuration = client.v1.billing_portal.configurations.create(
        {
            "features": {
                "invoice_history": {"enabled": True},
                "payment_method_update": {"enabled": True},
                "subscription_update": {"enabled": False},
                "subscription_cancel": {"enabled": False},
            },
            "login_page": {"enabled": False},
            "metadata": {"pumpkit_verification": "558-customer-actions"},
        }
    )
    monkeypatch.setattr(settings, "STRIPE_COUPON_PORTAL_CONFIGURATION_ID", configuration.id)
    yield configuration
    if not configuration.is_default:
        client.v1.billing_portal.configurations.update(configuration.id, {"active": False})


@pytest.mark.parametrize(
    "interval,coverage",
    [
        (interval, coverage)
        for interval in ("month", "year")
        for coverage in (
            "paid",
            "trial",
            "queued-free",
            "current-free",
            "cancelled",
            "past-due",
            "seller-paid",
            "queued-free-cancelled",
            "current-free-cancelled",
        )
    ]
    + [("month", "pending-coupon-free")],
)
async def test_restricted_card_update_preserves_confirmed_access_and_allowance(
    provider,
    authed_client,
    db,
    user,
    coupons,
    fake_billing,
    fixed_clock,
    monkeypatch,
    tmp_path,
    record,
    interval,
    coverage,
    restricted_configuration,
):
    client, prices, _ = provider
    monkeypatch.setattr(settings, "STRIPE_MANAGED_PAYMENTS", True)
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "whsec_558")
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 500)
    run = uuid4().hex
    keys = [f"pumpkit558_{run}_{interval}" for interval in ("month", "year")]
    for price_interval, key in zip(("month", "year"), keys, strict=True):
        client.v1.prices.update(prices[price_interval], {"lookup_key": key})
    monkeypatch.setattr(settings, "BILLING_PLAN_KEYS", keys)
    gateway = (
        LostDeferralResponseGateway(client)
        if coverage == "pending-coupon-free"
        else StripeBillingGateway(client)
    )
    fake_billing.plans = await gateway.list_plans(keys)
    monkeypatch.setitem(app.dependency_overrides, get_billing_gateway, lambda: gateway)
    now = int(time.time())
    fixed_clock.advance(datetime.fromtimestamp(now, timezone.utc) - fixed_clock())
    clock = client.v1.test_helpers.test_clocks.create(
        {"frozen_time": now, "name": "pumpkit-558-hosted-actions"}
    )
    try:
        customer = client.v1.customers.create(
            {"test_clock": clock.id, "email": "pumpkit558-actions@example.com"}
        ).id
        user.stripe_customer_id = customer
        await db.commit()
        if coverage == "seller-paid":
            method = client.v1.payment_methods.attach("pm_card_visa", {"customer": customer})
            subscription = client.v1.subscriptions.create(
                {
                    "customer": customer,
                    "items": [{"price": prices[interval]}],
                    "default_payment_method": method.id,
                }
            ).id
        else:
            checkout = await gateway.create_subscription_checkout(
                customer_id=customer,
                price_id=prices[interval],
                quantity=1,
                user_id=user.id,
                trial_period_days=7,
            )
            session = complete_checkout(
                client, checkout.id, checkout.url, decline_after_setup=coverage == "past-due"
            )
            subscription = session["subscription"]
            if coverage != "trial":
                await gateway.end_trial(subscription_id=subscription)
        await deliver_subscription_nudge(authed_client, customer, subscription)
        old_portal_url = ""
        paid_usage = (await authed_client.get("/api/v1/usage")).json()
        if coverage == "pending-coupon-free":
            old_portal = await authed_client.post("/api/v1/billing/portal")
            assert old_portal.status_code == 200, old_portal.text
            old_portal_url = old_portal.json()["url"]
        offer: dict[str, Any] = {}
        if "free" in coverage:
            created = await coupons("--months", "1")
            preview = await authed_client.post(PREVIEW, json={"code": created["code"]})
            assert preview.status_code == 200, preview.text
            offer = preview.json()
            redeemed = await authed_client.post(REDEEM, json=confirmation(offer))
            assert redeemed.status_code == 200, redeemed.text
            assert redeemed.json()["status"] == (
                "pending" if coverage == "pending-coupon-free" else "completed"
            )
            if coverage == "pending-coupon-free":
                blocked = await authed_client.post("/api/v1/billing/portal")
                assert blocked.status_code == 409
            if coverage.startswith("current-free"):
                target = (
                    int(
                        datetime.fromisoformat(
                            offer["starts_at"].replace("Z", "+00:00")
                        ).timestamp()
                    )
                    + 60
                )
                reach_payment_date(client, clock.id, target, interval)
                fixed_clock.advance(at(target) - fixed_clock())
                await deliver_subscription_nudge(authed_client, customer, subscription)
        if "cancelled" in coverage:
            cancelled = await authed_client.post("/api/v1/billing/cancel-renewal")
            assert cancelled.status_code == 200, cancelled.text
        before = subscription_facts(client, subscription)
        assert before["interval"] == interval
        assert before["managed_payments"] is (coverage != "seller-paid")
        if "free" in coverage:
            assert before["trial_end"] == int(
                datetime.fromisoformat(offer["ends_at"].replace("Z", "+00:00")).timestamp()
            )
        billing = (await authed_client.get("/api/v1/billing/me")).json()
        usage = (await authed_client.get("/api/v1/usage")).json()
        assert billing["subscribed"] is True
        assert billing["subscription"]["status"] == (
            "trialing"
            if ("free" in coverage and coverage != "pending-coupon-free") or coverage == "trial"
            else "past_due"
            if coverage == "past-due"
            else "active"
        )
        assert usage["allowance"]["generations"]["limit"] == (125 if coverage == "trial" else 500)
        if coverage.startswith("queued-free"):
            assert billing["free_access"]["queued_starts_at"] == offer["starts_at"]
        if coverage.startswith("current-free"):
            assert billing["free_access"]["current_starts_at"] == offer["starts_at"]
        if "cancelled" in coverage:
            assert billing["subscription"]["cancel_at"] is not None
        if old_portal_url:
            portal_url = old_portal_url
        else:
            opened = await authed_client.post("/api/v1/billing/portal")
            assert opened.status_code == 200, opened.text
            portal_url = opened.json()["url"]
        ledger = tmp_path / "private-portal.json"
        descriptor = os.open(ledger, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump({"url": portal_url, "livemode": False}, stream)
        controls = portal_browser(ledger, "inspect")
        assert controls == {"card_update": True, "cancel": False, "price_change": False}
        original_method = client.v1.subscriptions.retrieve(subscription).default_payment_method
        if coverage == "past-due":
            portal_browser(ledger, "generic")
            portal_browser(ledger, "existing")
        else:
            portal_browser(ledger, "new")
        replacement = client.v1.subscriptions.retrieve(subscription).default_payment_method
        assert replacement and replacement != original_method
        after = subscription_facts(client, subscription)
        if coverage == "past-due":
            for field in (
                "trial_end",
                "billing_cycle_anchor",
                "cancel_at",
                "cancel_at_period_end",
                "interval",
                "current_period_end",
            ):
                assert after[field] == before[field]
            invoice = client.v1.subscriptions.retrieve(subscription).latest_invoice
            assert client.v1.invoices.retrieve(str(invoice)).status == "paid"
        else:
            assert after == before
        await deliver_subscription_nudge(authed_client, customer, subscription)
        confirmed = (await authed_client.get("/api/v1/billing/me")).json()
        confirmed_usage = (await authed_client.get("/api/v1/usage")).json()
        if coverage == "pending-coupon-free":
            recovered = await authed_client.get(REDEEM + "/redeem-test-0001")
            assert recovered.status_code == 200, recovered.text
            assert recovered.json()["status"] == "completed"
            assert (
                await authed_client.get(REDEEM + "/redeem-test-0001")
            ).json() == recovered.json()
            assert isinstance(gateway, LostDeferralResponseGateway)
            assert gateway.calls == 1
            assert confirmed["subscribed"] is True
            assert confirmed["pending_coupon_operation"] is False
            assert confirmed["free_access"]["months"] == 1
            assert confirmed["free_access"]["queued_starts_at"] == offer["starts_at"]
            assert confirmed["free_access"]["ends_at"] == offer["ends_at"]
            assert confirmed_usage == paid_usage
        elif coverage == "past-due":
            assert confirmed["subscribed"] is True
            assert confirmed["subscription"]["status"] == "active"
            for field in ("generations", "x_posts", "link_x_posts", "resets_at"):
                assert confirmed_usage["allowance"][field] == usage["allowance"][field]
        else:
            assert confirmed == billing
            assert confirmed_usage == usage
        if coverage != "past-due":
            target = before["current_period_end"] + 3600
            reach_payment_date(client, clock.id, target, interval)
            fixed_clock.advance(at(target) - fixed_clock())
        charges = [
            charge.to_dict()
            for charge in client.v1.charges.list({"customer": customer, "limit": 100})
            if charge.paid and charge.payment_method == replacement
        ]
        expected_amounts = (
            [] if "cancelled" in coverage else [1900 if interval == "month" else 19000]
        )
        assert [charge["amount"] for charge in charges] == expected_amounts
        await deliver_subscription_nudge(authed_client, customer, subscription)
        future_billing = (await authed_client.get("/api/v1/billing/me")).json()
        future_usage = (await authed_client.get("/api/v1/usage")).json()
        assert future_billing["subscribed"] is ("cancelled" not in coverage)
        if "cancelled" not in coverage:
            assert future_usage["allowance"]["generations"]["limit"] == 500
        record.append(
            {
                "case": f"{interval}-{coverage}",
                "portal_card_update": True,
                "portal_cancel_control_absent": True,
                "portal_price_change_control_absent": True,
                "provider_dates_preserved": True,
                "unexpected_charge": False,
                "overdue_invoice_settled": coverage == "past-due",
                "replacement_paid_amounts": expected_amounts,
                "access_after_agreed_payment_date": future_billing["subscribed"],
                "billing_access_allowance_preserved": True,
                "sync": "test-signed webhook reads current real Stripe state",
                "webhook_replay_idempotent": True,
                "provider_before": {
                    field: before[field]
                    for field in (
                        "status",
                        "managed_payments",
                        "interval",
                        "trial_end",
                        "current_period_end",
                        "billing_cycle_anchor",
                        "cancel_at",
                        "cancel_at_period_end",
                        "charged",
                    )
                },
                "provider_after": {
                    field: after[field]
                    for field in (
                        "status",
                        "managed_payments",
                        "interval",
                        "trial_end",
                        "current_period_end",
                        "billing_cycle_anchor",
                        "cancel_at",
                        "cancel_at_period_end",
                        "charged",
                    )
                },
                "allowance_limit_before": usage["allowance"]["generations"]["limit"],
                "allowance_limit_after": confirmed_usage["allowance"]["generations"]["limit"],
            }
        )
    finally:
        client.v1.test_helpers.test_clocks.delete(clock.id)
