"""
Opt-in Stripe test-mode check of paid signup, Subscribe now, Coupon deferral, plan change, cancel_at
and Top-up refunds on Managed Payments Subscriptions; e2e/README.md says how to run it.
"""

import asyncio
import json
import os
import subprocess
import time
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import pytest
import stripe
from stripe.params import PriceCreateParams

from pumpkit.billing.gateway import TRIAL_END_FLOOR, BillingProviderError, StripeBillingGateway
from pumpkit.core.config import settings

KEY = os.environ.get("PUMPKIT_STRIPE_TEST_KEY", "")
RESULTS = os.environ.get("PUMPKIT_STRIPE_RESULTS")
pytestmark = pytest.mark.skipif(not KEY, reason="requires explicit Stripe test-mode credential")
CHECKOUT_SCRIPT = Path(__file__).resolve().parents[3] / "e2e" / "stripe-checkout.mjs"
# Software as a service, business use: eligible for Managed Payments.
TAX_CODE = "txcd_10103001"
MONTHLY, ANNUAL, TOP_UP = 1900, 19000, 1000
# Pumpkit opens the paid signup Checkout at least the trial end floor plus 5 minutes before Free access ends.
FIRST_PAYMENT_LEAD = int((TRIAL_END_FLOOR + timedelta(minutes=5)).total_seconds())


@pytest.fixture(scope="module")
def record():
    entries: list[dict[str, Any]] = []
    yield entries
    if RESULTS:
        descriptor = os.open(RESULTS, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(entries, stream, indent=2, default=str)


@pytest.fixture(scope="module")
def provider():
    if not KEY.startswith(("sk_test_", "rk_test_")):
        pytest.fail("Only Stripe test-mode credentials are accepted")
    client = stripe.StripeClient(KEY, max_network_retries=0)
    if client.v1.balance.retrieve().livemode is not False:
        pytest.fail("Provider account must be in test mode")
    created: dict[str, list[str]] = {"products": [], "prices": [], "customers": []}
    try:
        plan = client.v1.products.create(
            {"name": "Pumpkit Managed Payments verification", "tax_code": TAX_CODE}
        )
        created["products"].append(plan.id)
        top_up = client.v1.products.create(
            {"name": "Pumpkit Managed Payments Top-up verification", "tax_code": TAX_CODE}
        )
        created["products"].append(top_up.id)
        prices: dict[str, str] = {}
        for name, product, amount in [
            ("month", plan.id, MONTHLY),
            ("year", plan.id, ANNUAL),
            ("top_up", top_up.id, TOP_UP),
        ]:
            params: PriceCreateParams = {
                "product": product,
                "currency": "eur",
                "unit_amount": amount,
                "tax_behavior": "inclusive",
            }
            if name != "top_up":
                params["recurring"] = {"interval": "month" if name == "month" else "year"}
            prices[name] = client.v1.prices.create(params).id
            created["prices"].append(prices[name])
        yield client, prices, created["customers"]
    finally:
        # Deleting a customer cancels its Subscriptions.
        for customer in created["customers"]:
            best_effort(client.v1.customers.delete, customer)
        for price in created["prices"]:
            best_effort(client.v1.prices.update, price, {"active": False})
        for product in created["products"]:
            best_effort(client.v1.products.update, product, {"active": False})


def best_effort(cleanup: Callable[..., Any], *args: Any) -> None:
    try:
        cleanup(*args)
    except stripe.StripeError as error:
        warnings.warn(f"Stripe cleanup {args[0]} failed: {error}", stacklevel=2)


@pytest.fixture
def managed(monkeypatch, provider):
    monkeypatch.setattr(settings, "STRIPE_MANAGED_PAYMENTS", True)
    client, prices, customers = provider
    return client, prices, customers, StripeBillingGateway(client)


def complete_checkout(
    client: stripe.StripeClient, session_id: str, url: str, *, decline_after_setup: bool = False
) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "node",
            str(CHECKOUT_SCRIPT),
            "-",
            "decline-after-setup" if decline_after_setup else "success",
        ],
        input=url,
        text=True,
        capture_output=True,
        cwd=CHECKOUT_SCRIPT.parent,
        timeout=180,
    )
    if completed.returncode:
        pytest.fail("Synthetic hosted Checkout failed; no bearer URL is included in test output")
    for _ in range(30):
        session = client.v1.checkout.sessions.retrieve(session_id).to_dict()
        if session["status"] == "complete":
            return session
        time.sleep(1)
    pytest.fail(f"Checkout {session_id} did not complete")


async def eventually(read: Callable[[], Awaitable[list[Any]]], ready: Callable[[Any], bool]) -> Any:
    # Stripe's list endpoints lag a few seconds behind the objects they list.
    found: list[Any] = []
    for _ in range(30):
        found = await read()
        if len(found) == 1 and ready(found[0]):
            return found[0]
        await asyncio.sleep(1)
    pytest.fail(f"Stripe never listed the expected object: {found}")


def subscription_facts(client: stripe.StripeClient, subscription_id: str) -> dict[str, Any]:
    subscription = client.v1.subscriptions.retrieve(subscription_id).to_dict()
    item = subscription["items"]["data"][0]
    invoices = [
        invoice.to_dict()
        for invoice in client.v1.invoices.list({"subscription": subscription_id, "limit": 100})
    ]
    return {
        "status": subscription["status"],
        "managed_payments": (subscription.get("managed_payments") or {}).get("enabled"),
        "trial_end": subscription.get("trial_end"),
        "billing_cycle_anchor": subscription["billing_cycle_anchor"],
        "cancel_at": subscription.get("cancel_at"),
        "cancel_at_period_end": subscription["cancel_at_period_end"],
        "interval": item["price"]["recurring"]["interval"],
        "current_period_end": item["current_period_end"],
        "metadata": subscription.get("metadata"),
        "charged": [
            {"amount_paid": invoice["amount_paid"], "tax": bool(invoice.get("total_taxes"))}
            for invoice in invoices
            if invoice["amount_due"]
        ],
    }


async def attempt(
    record: list[dict[str, Any]],
    case: str,
    call: Awaitable[Any],
    client: stripe.StripeClient,
    subscription_id: Optional[str],
) -> Any:
    entry: dict[str, Any] = {"case": case}
    record.append(entry)
    try:
        result = await call
    except BillingProviderError as error:
        entry.update(accepted=False, error=str(error.__cause__ or error))
        raise
    entry["accepted"] = True
    if subscription_id:
        entry["state"] = subscription_facts(client, subscription_id)
    return result


def advance(client: stripe.StripeClient, clock: str, target: int) -> None:
    client.v1.test_helpers.test_clocks.advance(clock, {"frozen_time": target})
    for _ in range(90):
        if client.v1.test_helpers.test_clocks.retrieve(clock).status == "ready":
            return
        time.sleep(1)
    pytest.fail("Stripe test clock did not become ready within 90 seconds")


def at(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, timezone.utc)


async def new_customer(gateway: StripeBillingGateway, customers: list[str], case: str) -> str:
    customer = await gateway.create_customer(
        email=f"managed-payments-{case}@example.com",
        name="Synthetic Managed Payments verification",
        user_id=f"managed-payments-{case}",
        idempotency_key=f"managed-payments-{case}-{time.time_ns()}",
    )
    customers.append(customer)
    return customer


async def test_arranged_paid_subscription_takes_every_free_access_update(managed, record):
    client, prices, customers, gateway = managed
    customer = await new_customer(gateway, customers, "paid-signup")
    now = int(time.time())
    agreed = now + FIRST_PAYMENT_LEAD
    operation = f"verify-paid-signup-{now}"
    checkout = await attempt(
        record,
        "paid signup Checkout opened 48h05m before the agreed payment",
        gateway.create_paid_signup_checkout(
            customer_id=customer,
            user_id="managed-payments-paid-signup",
            operation_id=operation,
            price_id=prices["month"],
            first_payment_at=at(agreed),
            expires_at=at(now + 23 * 3600),
        ),
        client,
        None,
    )
    assert checkout.url
    session = complete_checkout(client, checkout.id, checkout.url)
    record[-1]["checkout"] = {k: session.get(k) for k in ("status", "payment_status")}
    listed = await eventually(
        lambda: gateway.list_paid_signup_checkouts(customer_id=customer),
        lambda found: found.status == "complete" and found.subscription_id,
    )
    subscription = listed.subscription_id
    started = subscription_facts(client, subscription)
    record.append({"case": "paid signup Subscription after Checkout", "state": started})
    assert started["managed_payments"] is True
    assert started["status"] == "trialing"
    assert started["trial_end"] == started["billing_cycle_anchor"] == agreed
    assert started["metadata"] == {"pumpkit_paid_signup": operation}
    assert started["charged"] == []

    deferred = agreed + 30 * 86400
    await attempt(
        record,
        "Coupon deferral by trial_end during Free access",
        gateway.defer_renewal(
            subscription_id=subscription, target=at(deferred), operation_id=f"{operation}-coupon"
        ),
        client,
        subscription,
    )
    facts = record[-1]["state"]
    assert facts["status"] == "trialing"
    assert facts["trial_end"] == facts["billing_cycle_anchor"] == deferred
    assert facts["charged"] == []

    item = client.v1.subscriptions.retrieve(subscription).to_dict()["items"]["data"][0]["id"]
    await attempt(
        record,
        "monthly to annual, payment date kept, no proration",
        gateway.change_plan(
            subscription_id=subscription,
            item_id=item,
            price_id=prices["year"],
            operation_id=f"{operation}-annual",
            first_payment_at=at(deferred),
        ),
        client,
        subscription,
    )
    facts = record[-1]["state"]
    assert facts["interval"] == "year"
    assert facts["trial_end"] == facts["billing_cycle_anchor"] == deferred
    assert facts["charged"] == []

    await attempt(
        record,
        "annual to monthly, payment date kept, no proration",
        gateway.change_plan(
            subscription_id=subscription,
            item_id=item,
            price_id=prices["month"],
            operation_id=f"{operation}-monthly",
            first_payment_at=at(deferred),
        ),
        client,
        subscription,
    )
    facts = record[-1]["state"]
    assert facts["interval"] == "month"
    assert facts["trial_end"] == facts["billing_cycle_anchor"] == deferred
    assert facts["charged"] == []

    await attempt(
        record,
        "cancel_at the end of Free access",
        gateway.cancel_renewal(subscription_id=subscription, ends_at=at(deferred)),
        client,
        subscription,
    )
    facts = record[-1]["state"]
    assert facts["status"] == "trialing"
    assert facts["cancel_at"] == deferred
    assert facts["charged"] == []

    portal = await attempt(
        record,
        "Billing portal session for the Managed Payments customer",
        gateway.create_portal_url(customer_id=customer),
        client,
        None,
    )
    assert portal.startswith("https://billing.stripe.com/")


async def test_paid_signup_completed_23h50m_late_charges_at_the_agreed_second(managed, record):
    client, prices, _, gateway = managed
    now = int(time.time())
    clock = client.v1.test_helpers.test_clocks.create({"frozen_time": now, "name": "pumpkit-mp"})
    try:
        customer = client.v1.customers.create(
            {"test_clock": clock.id, "email": "managed-payments-late@example.com"}
        ).id
        agreed = now + FIRST_PAYMENT_LEAD
        checkout = await attempt(
            record,
            "paid signup Checkout completed with trial_end 24h15m away (test clock)",
            gateway.create_paid_signup_checkout(
                customer_id=customer,
                user_id="managed-payments-late",
                operation_id=f"verify-late-signup-{now}",
                price_id=prices["month"],
                first_payment_at=at(agreed),
                expires_at=at(now + 23 * 3600 + 55 * 60),
            ),
            client,
            None,
        )
        assert checkout.url
        # The User finishes Checkout just before it expires, with trial_end then under 48 hours away.
        late = now + 23 * 3600 + 50 * 60
        advance(client, clock.id, late)
        complete_checkout(client, checkout.id, checkout.url)
        listed = await eventually(
            lambda: gateway.list_paid_signup_checkouts(customer_id=customer),
            lambda found: found.status == "complete" and found.subscription_id,
        )
        started = subscription_facts(client, listed.subscription_id)
        record[-1]["state"] = started
        assert started["status"] == "trialing"
        assert started["trial_end"] == started["billing_cycle_anchor"] == agreed
        advance(client, clock.id, agreed + 3600)
        charged = subscription_facts(client, listed.subscription_id)
        record.append({"case": "first payment at the agreed second", "state": charged})
        assert charged["status"] == "active"
        assert charged["charged"] == [{"amount_paid": MONTHLY, "tax": True}]
    finally:
        best_effort(client.v1.test_helpers.test_clocks.delete, clock.id)


async def test_cancel_signup_expires_the_paid_signup_checkout(managed, record):
    client, prices, customers, gateway = managed
    customer = await new_customer(gateway, customers, "cancel-signup")
    now = int(time.time())
    checkout = await attempt(
        record,
        "paid signup Checkout to cancel",
        gateway.create_paid_signup_checkout(
            customer_id=customer,
            user_id="managed-payments-cancel-signup",
            operation_id=f"verify-cancel-signup-{now}",
            price_id=prices["month"],
            first_payment_at=at(now + FIRST_PAYMENT_LEAD),
            expires_at=at(now + 23 * 3600),
        ),
        client,
        None,
    )
    await attempt(
        record,
        "Cancel signup expires the open paid signup Checkout",
        gateway.expire_paid_signup_checkout(session_id=checkout.id),
        client,
        None,
    )
    [listed] = await gateway.list_paid_signup_checkouts(customer_id=customer)
    record[-1]["checkout_status"] = listed.status
    assert listed.status == "expired"


async def test_paid_subscription_takes_subscribe_now_deferral_and_cancellation(managed, record):
    client, prices, customers, gateway = managed
    customer = await new_customer(gateway, customers, "subscriber")
    checkout = await attempt(
        record,
        "Checkout for a Subscription with a 7-day Trial",
        gateway.create_subscription_checkout(
            customer_id=customer,
            price_id=prices["month"],
            quantity=1,
            user_id="managed-payments-subscriber",
            trial_period_days=7,
        ),
        client,
        None,
    )
    complete_checkout(client, checkout.id, checkout.url)
    state = await eventually(lambda: gateway.list_subscriptions(customer_id=customer), bool)
    subscription = state.id
    started = subscription_facts(client, subscription)
    record.append({"case": "Subscription with a Trial after Checkout", "state": started})
    assert started["managed_payments"] is True
    assert started["status"] == "trialing"

    authentication = await attempt(
        record,
        "Subscribe now ends the Trial (trial_end=now)",
        gateway.end_trial(subscription_id=subscription),
        client,
        subscription,
    )
    facts = record[-1]["state"]
    assert authentication is None
    assert facts["status"] == "active"
    assert [charge["amount_paid"] for charge in facts["charged"]] == [MONTHLY]
    paid_end = facts["current_period_end"]

    deferred = paid_end + 30 * 86400
    await attempt(
        record,
        "Coupon deferral by trial_end after paid coverage",
        gateway.defer_renewal(
            subscription_id=subscription,
            target=at(deferred),
            operation_id=f"verify-subscriber-coupon-{subscription}",
        ),
        client,
        subscription,
    )
    facts = record[-1]["state"]
    assert facts["status"] == "trialing"
    assert facts["trial_end"] == facts["billing_cycle_anchor"] == deferred
    assert [charge["amount_paid"] for charge in facts["charged"]] == [MONTHLY]

    item = client.v1.subscriptions.retrieve(subscription).to_dict()["items"]["data"][0]["id"]
    await attempt(
        record,
        "monthly to annual during deferral after paid coverage",
        gateway.change_plan(
            subscription_id=subscription,
            item_id=item,
            price_id=prices["year"],
            operation_id=f"verify-subscriber-annual-{subscription}",
            first_payment_at=at(deferred),
        ),
        client,
        subscription,
    )
    facts = record[-1]["state"]
    assert facts["interval"] == "year"
    assert facts["trial_end"] == deferred
    assert [charge["amount_paid"] for charge in facts["charged"]] == [MONTHLY]

    await attempt(
        record,
        "cancel_at the end of deferred coverage",
        gateway.cancel_renewal(subscription_id=subscription, ends_at=at(deferred)),
        client,
        subscription,
    )
    facts = record[-1]["state"]
    assert facts["cancel_at"] == deferred
    assert [charge["amount_paid"] for charge in facts["charged"]] == [MONTHLY]


async def test_refunded_top_up_reads_as_reversed(managed, record):
    client, prices, customers, gateway = managed
    customer = await new_customer(gateway, customers, "top-up")
    checkout = await attempt(
        record,
        "Top-up Checkout",
        gateway.create_top_up_checkout(
            customer_id=customer, price_id=prices["top_up"], user_id="managed-payments-top-up"
        ),
        client,
        None,
    )
    complete_checkout(client, checkout.id, checkout.url)
    paid = await eventually(lambda: gateway.list_top_ups(customer_id=customer), bool)
    assert paid.reversed is False and paid.charge_id
    refund = client.v1.refunds.create({"charge": paid.charge_id})
    refunded = await eventually(
        lambda: gateway.list_top_ups(customer_id=customer), lambda found: found.reversed
    )
    charge_customer = await gateway.get_charge_customer(charge_id=paid.charge_id)
    record.append(
        {
            "case": "refund of a Top-up payment, read through list_top_ups",
            "accepted": True,
            "refund_status": refund.status,
            "reversed": refunded.reversed,
            "charge_customer": charge_customer,
        }
    )
    assert refunded.reversed is True
    assert charge_customer == customer


@pytest.mark.parametrize(
    "case", ["trial", "paid-up", "past-due", "cancelled", "free-access", "trial-new"]
)
async def test_restricted_portal_replaces_the_subscription_payment_method(
    managed, record, tmp_path, case
):
    client, prices, _, gateway = managed
    now = int(time.time())
    clock = client.v1.test_helpers.test_clocks.create(
        {"frozen_time": now, "name": "pumpkit-card-proof"}
    )
    configuration = None
    try:
        customer = client.v1.customers.create(
            {"test_clock": clock.id, "email": "managed-card-proof@example.com"}
        ).id
        checkout = await gateway.create_subscription_checkout(
            customer_id=customer,
            price_id=prices["month"],
            quantity=1,
            user_id="synthetic-card-proof",
            trial_period_days=7,
        )
        session = complete_checkout(
            client, checkout.id, checkout.url, decline_after_setup=case == "past-due"
        )
        subscription_id = session["subscription"]
        subscription = client.v1.subscriptions.retrieve(subscription_id).to_dict()
        assert subscription["managed_payments"]["enabled"] is True
        original = subscription["default_payment_method"]
        if case in {"paid-up", "past-due", "cancelled"}:
            await gateway.end_trial(subscription_id=subscription_id)
        if case == "free-access":
            await gateway.defer_renewal(
                subscription_id=subscription_id,
                target=at(subscription["trial_end"] + 30 * 86400),
                operation_id=f"card-proof-{subscription_id}",
            )
        subscription = client.v1.subscriptions.retrieve(subscription_id).to_dict()
        if case == "cancelled":
            await gateway.cancel_renewal(
                subscription_id=subscription_id,
                ends_at=at(subscription["items"]["data"][0]["current_period_end"]),
            )
        before = subscription_facts(client, subscription_id)
        assert before["status"] == (
            "past_due"
            if case == "past-due"
            else "active"
            if case in {"paid-up", "cancelled"}
            else "trialing"
        )
        configuration = client.v1.billing_portal.configurations.create(
            {
                "features": {
                    "invoice_history": {"enabled": True},
                    "payment_method_update": {"enabled": True},
                    "subscription_update": {"enabled": False},
                    "subscription_cancel": {"enabled": False},
                },
                "login_page": {"enabled": False},
                "metadata": {"pumpkit_verification": "subscription-card-proof"},
            }
        )
        portal = client.v1.billing_portal.sessions.create(
            {
                "customer": customer,
                "configuration": configuration.id,
                "locale": "en",
                "return_url": "https://example.com/card-proof",
            }
        )
        ledger = tmp_path / "private-portal.json"
        descriptor = os.open(ledger, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump({"url": portal.url, "livemode": False}, stream)
        subprocess.run(
            [
                "node",
                str(CHECKOUT_SCRIPT.with_name("stripe-payment-method.mjs")),
                str(ledger),
                "generic",
            ],
            check=True,
            timeout=120,
        )
        customer_default = client.v1.customers.retrieve(customer).to_dict()["invoice_settings"][
            "default_payment_method"
        ]
        assert customer_default and customer_default != original
        assert client.v1.subscriptions.retrieve(subscription_id).default_payment_method == original
        negative_charge_uses_original = None
        if case == "paid-up":
            advance(client, clock.id, before["current_period_end"] + 3600)
            negative_charges = [
                charge.to_dict()
                for charge in client.v1.charges.list({"customer": customer, "limit": 100})
                if charge.paid
            ]
            assert len(negative_charges) == 2
            assert all(charge["payment_method"] == original for charge in negative_charges)
            negative_charge_uses_original = True
            before = subscription_facts(client, subscription_id)
        record.append(
            {
                "case": f"{case}: generic Customer-default negative control",
                "subsequent_charge_uses_original": negative_charge_uses_original,
                "customer_changed": True,
                "subscription_changed": False,
            }
        )
        subprocess.run(
            [
                "node",
                str(CHECKOUT_SCRIPT.with_name("stripe-payment-method.mjs")),
                str(ledger),
                "new" if case == "trial-new" else "existing",
            ],
            check=True,
            timeout=120,
        )
        after = subscription_facts(client, subscription_id)
        replacement = client.v1.subscriptions.retrieve(subscription_id).default_payment_method
        assert replacement and replacement != original
        if case != "trial-new":
            assert replacement == customer_default
        for field in (
            "trial_end",
            "billing_cycle_anchor",
            "cancel_at",
            "cancel_at_period_end",
            "current_period_end",
            "interval",
        ):
            assert after[field] == before[field]
        if case != "past-due":
            assert after["charged"] == before["charged"]
        if case == "past-due":
            invoice = client.v1.subscriptions.retrieve(subscription_id).latest_invoice
            if client.v1.invoices.retrieve(str(invoice)).status != "paid":
                client.v1.invoices.pay(str(invoice))
        else:
            target = before["current_period_end"] + 3600
            advance(client, clock.id, target)
        final = subscription_facts(client, subscription_id)
        charges = [
            charge.to_dict()
            for charge in client.v1.charges.list({"customer": customer, "limit": 100})
            if charge.paid
        ]
        replacement_charges = [
            charge for charge in charges if charge["payment_method"] == replacement
        ]
        if case == "cancelled":
            assert final["status"] == "canceled"
            assert replacement_charges == []
        else:
            assert final["status"] == "active"
            assert len(replacement_charges) == 1
            assert replacement_charges[0]["amount"] == MONTHLY
        record.append(
            {
                "case": f"{case}: subscription-scoped card replacement",
                "method_replaced": True,
                "dates_and_cancellation_preserved": True,
                "replacement_paid_amounts": [charge["amount"] for charge in replacement_charges],
                "final_status": final["status"],
            }
        )
    finally:
        cleanup_failures = []
        if configuration and not configuration.is_default:
            try:
                client.v1.billing_portal.configurations.update(configuration.id, {"active": False})
            except stripe.StripeError:
                cleanup_failures.append("portal configuration")
        try:
            client.v1.test_helpers.test_clocks.delete(clock.id)
        except stripe.StripeError:
            cleanup_failures.append("test clock")
        if cleanup_failures:
            pytest.fail(f"Owned fixture cleanup incomplete: {', '.join(cleanup_failures)}")
