"""
The webhook-verification contract both adapters share: the fake signs events
the way Stripe does, so the Stripe adapter must accept them with the same
secret. No network: verification is local HMAC work. The Stripe adapter's
translation of Stripe's answers is checked against recorded Stripe responses.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

import pytest
import stripe

from pumpkit.billing.gateway import (
    BillingGateway,
    FakeBillingGateway,
    StripeBillingGateway,
    SubscriptionState,
    WebhookEvent,
    WebhookSignatureError,
)
from pumpkit.core.config import settings

SECRET = "whsec_contract"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(params=["stripe", "fake"])
def verifier(request, monkeypatch) -> BillingGateway:
    if request.param == "fake":
        return FakeBillingGateway(webhook_secret=SECRET)
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", SECRET)
    return StripeBillingGateway()


def _signed(
    secret: str = SECRET, data_object: Optional[dict[str, Any]] = None
) -> tuple[bytes, str]:
    return FakeBillingGateway(webhook_secret=secret).signed_event(
        event_id="evt_1",
        event_type="customer.subscription.updated",
        data_object=data_object or {"id": "sub_1", "customer": "cus_1", "status": "active"},
    )


@pytest.mark.parametrize(
    ("data_object", "customer_id"),
    [
        ({"id": "sub_1", "customer": "cus_1"}, "cus_1"),
        ({"id": "sub_1", "customer": {"id": "cus_1", "object": "customer"}}, "cus_1"),
        ({"id": "in_1"}, None),
    ],
    ids=["customer-id", "expanded-customer", "no-customer"],
)
def test_a_signed_event_verifies_into_its_id_type_and_customer(verifier, data_object, customer_id):
    payload, signature = _signed(data_object=data_object)

    event = verifier.verify_webhook(payload=payload, signature=signature)

    assert event == WebhookEvent(
        id="evt_1", type="customer.subscription.updated", customer_id=customer_id
    )


@pytest.mark.parametrize(
    "tamper",
    [
        lambda payload, signature: (payload, "t=1,v1=deadbeef"),
        lambda payload, signature: (payload, "garbage"),
        lambda payload, signature: (payload.replace(b"cus_1", b"cus_2"), signature),
        lambda payload, signature: (b"not json", signature),
        lambda payload, signature: _signed("whsec_someone_else"),
    ],
    ids=["wrong-signature", "malformed-header", "tampered-payload", "not-json", "other-secret"],
)
def test_an_unverifiable_event_is_rejected(verifier, tamper):
    payload, signature = tamper(*_signed())

    with pytest.raises(WebhookSignatureError):
        verifier.verify_webhook(payload=payload, signature=signature)


class _RecordedStripe(stripe.HTTPClient):
    """Stripe's HTTP layer, answering every request with one recorded response body."""

    name = "recorded"

    def __init__(self, body: str) -> None:
        super().__init__()
        self._body = body
        self.urls: list[str] = []
        self.methods: list[str] = []
        self.forms: list[dict[str, list[str]]] = []

    def request(self, method, url, headers, post_data=None, *, _usage=None):
        self.urls.append(url)
        self.methods.append(method)
        self.forms.append(parse_qs(post_data or ""))
        return self._body, 200, {}

    def close(self) -> None:
        pass


async def test_the_stripe_adapter_lists_every_subscription_of_a_customer():
    http = _RecordedStripe((FIXTURES / "stripe_subscription_list.json").read_text())
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))

    subscriptions = await gateway.list_subscriptions(customer_id="cus_Contract")

    assert subscriptions == [
        # The period end comes from the first item when the subscription has none.
        SubscriptionState(
            id="sub_1QaRunning",
            status="past_due",
            price_id="price_1Monthly",
            plan_key="pumpkit_pro_monthly",
            current_period_end=datetime(2025, 11, 6, tzinfo=timezone.utc),
            cancel_at_period_end=True,
            created_at=datetime(2025, 10, 6, tzinfo=timezone.utc),
            billing_cycle_anchor=datetime(2025, 10, 6, tzinfo=timezone.utc),
        ),
        SubscriptionState(
            id="sub_1QaEnded",
            status="canceled",
            price_id="price_1Legacy",
            plan_key=None,
            current_period_end=datetime(2025, 9, 1, tzinfo=timezone.utc),
            cancel_at_period_end=False,
            created_at=datetime(2025, 8, 1, tzinfo=timezone.utc),
            billing_cycle_anchor=datetime(2025, 8, 1, tzinfo=timezone.utc),
        ),
    ]
    [url] = http.urls
    query = parse_qs(urlsplit(url).query)
    # Stripe leaves cancelled Subscriptions out unless asked for all of them.
    assert query["status"] == ["all"]
    assert query["customer"] == ["cus_Contract"]


async def test_the_stripe_adapter_reads_a_trials_start_and_end():
    listing = json.loads((FIXTURES / "stripe_subscription_list.json").read_text())
    trialing = listing["data"][0]
    trialing.update(status="trialing", trial_start=1759708800, trial_end=1760313600)
    trialing["billing_cycle_anchor"] = 1760313600
    listing["data"] = [trialing]
    http = _RecordedStripe(json.dumps(listing))
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))

    [subscription] = await gateway.list_subscriptions(customer_id="cus_Contract")

    assert subscription.trial_start == datetime(2025, 10, 6, tzinfo=timezone.utc)
    assert subscription.trial_end == datetime(2025, 10, 13, tzinfo=timezone.utc)
    assert subscription.billing_cycle_anchor == datetime(2025, 10, 13, tzinfo=timezone.utc)


async def test_the_stripe_adapter_cancels_a_subscription_now():
    http = _RecordedStripe(
        '{"id": "sub_1Incomplete", "object": "subscription", "status": "canceled"}'
    )
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))

    await gateway.cancel_subscription(subscription_id="sub_1Incomplete")

    assert http.methods == ["delete"]
    assert urlsplit(http.urls[0]).path == "/v1/subscriptions/sub_1Incomplete"


async def test_the_stripe_adapter_ends_a_trial_now_and_keeps_the_update_if_the_charge_fails():
    listing = json.loads((FIXTURES / "stripe_subscription_list.json").read_text())
    http = _RecordedStripe(json.dumps(listing["data"][0]))
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))

    await gateway.end_trial(subscription_id="sub_1QaRunning")

    assert http.methods == ["post"]
    assert urlsplit(http.urls[0]).path == "/v1/subscriptions/sub_1QaRunning"
    [form] = http.forms
    assert form["trial_end"] == ["now"]
    assert form["payment_behavior"] == ["allow_incomplete"]


async def test_the_fake_ends_a_trial_at_its_clock_and_starts_the_paid_period():
    now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    gateway = FakeBillingGateway(clock=lambda: now)
    trialing = SubscriptionState(
        id="sub_1",
        status="trialing",
        price_id="price_monthly",
        plan_key="pumpkit_pro_monthly",
        current_period_end=datetime(2026, 10, 14, tzinfo=timezone.utc),
        cancel_at_period_end=False,
        created_at=datetime(2026, 10, 7, tzinfo=timezone.utc),
        trial_start=datetime(2026, 10, 7, tzinfo=timezone.utc),
        trial_end=datetime(2026, 10, 14, tzinfo=timezone.utc),
        billing_cycle_anchor=datetime(2026, 10, 14, tzinfo=timezone.utc),
    )
    gateway.set_subscription("cus_1", trialing)

    await gateway.end_trial(subscription_id="sub_1")

    [ended] = await gateway.list_subscriptions(customer_id="cus_1")
    assert (
        ended.status,
        ended.trial_end,
        ended.billing_cycle_anchor,
        ended.current_period_end,
    ) == (
        "active",
        now,
        now,
        datetime(2026, 11, 10, 12, tzinfo=timezone.utc),
    )
    assert gateway.ended_trials == ["sub_1"]


async def test_the_stripe_checkout_charges_vat_as_the_seller_and_collects_vat_ids():
    http = _RecordedStripe(
        '{"id": "cs_1", "object": "checkout.session", "url": "https://checkout.stripe.com/c/cs_1"}'
    )
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))

    await gateway.create_subscription_checkout(
        customer_id="cus_1", price_id="price_1Monthly", quantity=1, user_id="user_1"
    )

    [form] = http.forms
    assert form["automatic_tax[enabled]"] == ["true"]
    assert form["tax_id_collection[enabled]"] == ["true"]
    # Stripe refuses tax ID collection for an existing customer unless Checkout may save
    # the address and business name it collects onto that customer.
    assert form["customer_update[address]"] == ["auto"]
    assert form["customer_update[name]"] == ["auto"]
    # Stripe turns Managed Payments on by default for new accounts, which makes Stripe
    # the merchant of record and refuses products without a tax code.
    assert form["managed_payments[enabled]"] == ["false"]


async def test_the_fake_lists_a_cancelled_subscription_as_ended():
    gateway = FakeBillingGateway()
    incomplete = SubscriptionState(
        id="sub_1",
        status="incomplete",
        price_id="price_monthly",
        plan_key="pumpkit_pro_monthly",
        current_period_end=None,
        cancel_at_period_end=False,
        created_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
    )
    gateway.set_subscription("cus_1", incomplete)

    await gateway.cancel_subscription(subscription_id="sub_1")

    assert await gateway.list_subscriptions(customer_id="cus_1") == [
        SubscriptionState(
            id="sub_1",
            status="canceled",
            price_id="price_monthly",
            plan_key="pumpkit_pro_monthly",
            current_period_end=None,
            cancel_at_period_end=False,
            created_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
        )
    ]
    assert gateway.cancelled_subscriptions == ["sub_1"]
