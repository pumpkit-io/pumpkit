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
    BillingProviderError,
    DeferralRefused,
    FakeBillingGateway,
    OneOffPrice,
    StripeBillingGateway,
    SubscriptionState,
    TopUpPurchase,
    WebhookEvent,
    WebhookSignatureError,
    stripe_client,
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


def test_a_dispute_event_names_its_charge_for_want_of_a_customer(verifier):
    payload, signature = FakeBillingGateway(webhook_secret=SECRET).signed_event(
        event_id="evt_1",
        event_type="charge.dispute.created",
        data_object={"id": "dp_1", "object": "dispute", "charge": "ch_1"},
    )

    event = verifier.verify_webhook(payload=payload, signature=signature)

    assert event == WebhookEvent(
        id="evt_1", type="charge.dispute.created", customer_id=None, charge_id="ch_1"
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
    """Stripe's HTTP layer, answering with the recorded response bodies in turn, repeating the last."""

    name = "recorded"

    def __init__(self, *bodies: str) -> None:
        super().__init__()
        self._bodies = list(bodies)
        self.urls: list[str] = []
        self.methods: list[str] = []
        self.forms: list[dict[str, list[str]]] = []
        self.headers: list[dict[str, str]] = []

    def request(
        self, method, url, headers, post_data=None, *, _usage=None
    ) -> tuple[str, int, dict]:
        self.urls.append(url)
        self.methods.append(method)
        self.forms.append(parse_qs(post_data or ""))
        self.headers.append(dict(headers or {}))
        body = self._bodies.pop(0) if len(self._bodies) > 1 else self._bodies[0]
        return body, 200, {}

    def close(self) -> None:
        pass


async def test_the_stripe_adapter_lists_every_subscription_of_a_customer():
    http = _RecordedStripe((FIXTURES / "stripe_subscription_list.json").read_text())
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))

    subscriptions = await gateway.list_subscriptions(customer_id="cus_Contract")

    assert subscriptions == [
        # The period end comes from the first item when the subscription has none.
        SubscriptionState(
            item_id="si_1QaRunning",
            item_count=1,
            interval="month",
            interval_count=1,
            current_period_start=datetime(2025, 10, 6, tzinfo=timezone.utc),
            id="sub_1QaRunning",
            status="past_due",
            price_id="price_1Monthly",
            plan_key="pumpkit_pro_monthly",
            current_period_end=datetime(2025, 11, 6, tzinfo=timezone.utc),
            # Cancelled at its period end, the older way Stripe records a cancellation.
            cancel_at=datetime(2025, 11, 6, tzinfo=timezone.utc),
            created_at=datetime(2025, 10, 6, tzinfo=timezone.utc),
            billing_cycle_anchor=datetime(2025, 10, 6, tzinfo=timezone.utc),
        ),
        SubscriptionState(
            item_id="si_1QaEnded",
            item_count=1,
            interval="month",
            interval_count=1,
            current_period_start=datetime(2025, 8, 1, tzinfo=timezone.utc),
            id="sub_1QaEnded",
            status="canceled",
            price_id="price_1Legacy",
            plan_key=None,
            current_period_end=datetime(2025, 9, 1, tzinfo=timezone.utc),
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


async def test_the_stripe_adapter_reads_a_cancellation_set_as_a_date():
    """Flexible billing mode, and Stripe's cancellation page with it, set `cancel_at` instead."""
    listing = json.loads((FIXTURES / "stripe_subscription_list.json").read_text())
    trialing = listing["data"][0]
    trialing.update(status="trialing", cancel_at_period_end=False, cancel_at=1762387200)
    listing["data"] = [trialing]
    http = _RecordedStripe(json.dumps(listing))
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))

    [subscription] = await gateway.list_subscriptions(customer_id="cus_Contract")

    assert subscription.cancel_at == datetime(2025, 11, 6, tzinfo=timezone.utc)


async def test_the_stripe_adapter_reads_no_cancellation_on_a_renewing_subscription():
    listing = json.loads((FIXTURES / "stripe_subscription_list.json").read_text())
    renewing = listing["data"][0]
    renewing.update(status="active", cancel_at_period_end=False, cancel_at=None)
    listing["data"] = [renewing]
    http = _RecordedStripe(json.dumps(listing))
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))

    [subscription] = await gateway.list_subscriptions(customer_id="cus_Contract")

    assert subscription.cancel_at is None


async def test_the_stripe_adapter_cancels_a_subscription_now():
    http = _RecordedStripe(
        '{"id": "sub_1Incomplete", "object": "subscription", "status": "canceled"}'
    )
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))

    await gateway.cancel_subscription(subscription_id="sub_1Incomplete")

    assert http.methods == ["delete"]
    assert urlsplit(http.urls[0]).path == "/v1/subscriptions/sub_1Incomplete"


def _ended_trial(invoice: Optional[dict[str, Any]]) -> str:
    listing = json.loads((FIXTURES / "stripe_subscription_list.json").read_text())
    return json.dumps({**listing["data"][0], "latest_invoice": invoice})


def _invoice(status: str) -> dict[str, Any]:
    return {
        "id": "in_1First",
        "object": "invoice",
        "status": status,
        "hosted_invoice_url": "https://invoice.stripe.com/i/in_1First",
    }


def _payments(intent_status: str) -> str:
    return json.dumps(
        {
            "object": "list",
            "url": "/v1/invoice_payments",
            "has_more": False,
            "data": [
                {
                    "id": "inpay_1",
                    "object": "invoice_payment",
                    "invoice": "in_1First",
                    "status": "open",
                    "payment": {
                        "type": "payment_intent",
                        "payment_intent": {
                            "id": "pi_1",
                            "object": "payment_intent",
                            "status": intent_status,
                        },
                    },
                }
            ],
        }
    )


async def test_the_stripe_adapter_ends_a_trial_now_and_keeps_the_update_if_the_charge_fails():
    http = _RecordedStripe(_ended_trial(_invoice("open")), _payments("requires_payment_method"))
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))

    authentication_url = await gateway.end_trial(subscription_id="sub_1QaRunning")

    assert authentication_url is None
    assert http.methods[0] == "post"
    assert urlsplit(http.urls[0]).path == "/v1/subscriptions/sub_1QaRunning"
    form = http.forms[0]
    assert form["trial_end"] == ["now"]
    assert form["payment_behavior"] == ["allow_incomplete"]


async def test_a_cached_stripe_500_does_not_block_the_next_attempt_to_end_a_trial():
    class _CachesFirstFailure(_RecordedStripe):
        failed_key = None

        def request(self, method, url, headers, post_data=None, *, _usage=None):
            key = headers["Idempotency-Key"]
            if self.failed_key is None:
                self.failed_key = key
            if key == self.failed_key:
                return '{"error": {"message": "boom", "type": "api_error"}}', 500, {}
            return super().request(method, url, headers, post_data, _usage=_usage)

    http = _CachesFirstFailure(_ended_trial(_invoice("paid")))
    client = stripe.StripeClient("sk_test_contract", http_client=http, max_network_retries=0)
    gateway = StripeBillingGateway(client)

    with pytest.raises(BillingProviderError):
        await gateway.end_trial(subscription_id="sub_1QaRunning")

    assert await gateway.end_trial(subscription_id="sub_1QaRunning") is None


async def test_the_stripe_adapter_links_a_first_charge_that_needs_authentication():
    http = _RecordedStripe(_ended_trial(_invoice("open")), _payments("requires_action"))
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))

    authentication_url = await gateway.end_trial(subscription_id="sub_1QaRunning")

    assert authentication_url == "https://invoice.stripe.com/i/in_1First"
    query = parse_qs(urlsplit(http.urls[1]).query)
    assert urlsplit(http.urls[1]).path == "/v1/invoice_payments"
    assert query["invoice"] == ["in_1First"]


async def test_the_stripe_adapter_links_nothing_for_a_declined_first_charge():
    http = _RecordedStripe(_ended_trial(_invoice("open")), _payments("requires_payment_method"))
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))

    assert await gateway.end_trial(subscription_id="sub_1QaRunning") is None


async def test_the_stripe_adapter_links_nothing_when_it_cant_list_the_first_charges_payments():
    """The Trial has ended by then, so the caller must still hear back and sync."""

    class _FailsToList(_RecordedStripe):
        def request(self, method, url, headers, post_data=None, *, _usage=None):
            if "/v1/invoice_payments" in url:
                return '{"error": {"message": "boom", "type": "api_error"}}', 500, {}
            return super().request(method, url, headers, post_data, _usage=_usage)

    http = _FailsToList(_ended_trial(_invoice("open")))
    client = stripe.StripeClient("sk_test_contract", http_client=http, max_network_retries=0)
    gateway = StripeBillingGateway(client)

    assert await gateway.end_trial(subscription_id="sub_1QaRunning") is None


async def test_the_fake_ends_a_trial_at_its_clock_and_starts_the_paid_period():
    now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    gateway = FakeBillingGateway(clock=lambda: now)
    trialing = SubscriptionState(
        id="sub_1",
        status="trialing",
        price_id="price_monthly",
        plan_key="pumpkit_pro_monthly",
        current_period_end=datetime(2026, 10, 14, tzinfo=timezone.utc),
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

    gateway.clock = lambda: datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
    await gateway.end_trial(subscription_id="sub_1")

    assert await gateway.list_subscriptions(customer_id="cus_1") == [ended]
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


_CHECKOUT = (
    '{"id": "cs_1", "object": "checkout.session", "url": "https://checkout.stripe.com/c/cs_1"}'
)

# Stripe refuses these with Managed Payments on: it collects tax, VAT IDs and the address itself.
_SELLER_ONLY_PARAMS = ("automatic_tax", "tax_id_collection", "customer_update")


@pytest.mark.parametrize("trial_period_days", [None, 7], ids=["no-trial", "trial"])
async def test_a_managed_payments_subscription_checkout_lets_stripe_be_the_seller(
    monkeypatch, trial_period_days
):
    monkeypatch.setattr(settings, "STRIPE_MANAGED_PAYMENTS", True)
    gateway, http = _recorded_gateway(_CHECKOUT)

    await gateway.create_subscription_checkout(
        customer_id="cus_1",
        price_id="price_1Monthly",
        quantity=1,
        user_id="user_1",
        trial_period_days=trial_period_days,
    )

    [form] = http.forms
    assert form["managed_payments[enabled]"] == ["true"]
    assert not [key for key in form if key.startswith(_SELLER_ONLY_PARAMS)]
    assert form["mode"] == ["subscription"]
    assert form["customer"] == ["cus_1"]
    assert form["client_reference_id"] == ["user_1"]
    assert form["line_items[0][price]"] == ["price_1Monthly"]
    assert form["line_items[0][quantity]"] == ["1"]
    assert form["allow_promotion_codes"] == ["true"]
    assert form["success_url"] == ["http://localhost:5173/billing/success"]
    assert form["cancel_url"] == ["http://localhost:5173/billing/cancelled"]
    if trial_period_days is None:
        assert not [key for key in form if key.startswith("subscription_data")]
    else:
        assert form["subscription_data[trial_period_days]"] == ["7"]


async def test_a_managed_payments_top_up_checkout_lets_stripe_be_the_seller(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_MANAGED_PAYMENTS", True)
    gateway, http = _recorded_gateway(_CHECKOUT)

    await gateway.create_top_up_checkout(
        customer_id="cus_1", price_id="price_1TopUp", user_id="user_1"
    )

    [form] = http.forms
    assert form["managed_payments[enabled]"] == ["true"]
    assert not [key for key in form if key.startswith(_SELLER_ONLY_PARAMS)]
    assert form["mode"] == ["payment"]
    assert form["customer"] == ["cus_1"]
    assert form["client_reference_id"] == ["user_1"]
    assert form["line_items[0][price]"] == ["price_1TopUp"]
    assert form["line_items[0][quantity]"] == ["1"]
    assert form["metadata[pumpkit_purchase]"] == ["top_up"]
    assert form["success_url"] == ["http://localhost:5173/billing/top-up/success"]
    assert form["cancel_url"] == ["http://localhost:5173/billing"]


async def test_the_fake_lists_a_cancelled_subscription_as_ended():
    gateway = FakeBillingGateway()
    incomplete = SubscriptionState(
        id="sub_1",
        status="incomplete",
        price_id="price_monthly",
        plan_key="pumpkit_pro_monthly",
        current_period_end=None,
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
            created_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
        )
    ]
    assert gateway.cancelled_subscriptions == ["sub_1"]


def _recorded_gateway(body: str) -> tuple[StripeBillingGateway, _RecordedStripe]:
    http = _RecordedStripe(body)
    return StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http)), http


async def test_the_stripe_adapter_lists_paid_top_ups_with_their_refund_and_dispute_state():
    gateway, http = _recorded_gateway((FIXTURES / "stripe_top_up_checkout_list.json").read_text())

    top_ups = await gateway.list_top_ups(customer_id="cus_Contract")

    # Unpaid Checkouts and Subscription Checkouts are no Top-ups; a partial refund reverses one.
    assert top_ups == [
        TopUpPurchase(
            checkout_session_id="cs_1Paid",
            paid_at=datetime(2025, 10, 6, tzinfo=timezone.utc),
            reversed=False,
            charge_id="ch_1Paid",
        ),
        TopUpPurchase(
            checkout_session_id="cs_1Refunded",
            paid_at=datetime.fromtimestamp(1759000100, tz=timezone.utc),
            reversed=True,
            charge_id="ch_1Refunded",
        ),
        TopUpPurchase(
            checkout_session_id="cs_1Disputed",
            paid_at=datetime.fromtimestamp(1758000100, tz=timezone.utc),
            reversed=True,
            charge_id="ch_1Disputed",
        ),
    ]
    [url] = http.urls
    query = parse_qs(urlsplit(url).query)
    assert query["customer"] == ["cus_Contract"]
    assert query["status"] == ["complete"]
    assert query["expand[0]"] == ["data.payment_intent.latest_charge"]


async def test_the_stripe_adapter_resolves_only_a_one_off_price_for_the_top_up():
    one_off = {
        "id": "price_1TopUp",
        "object": "price",
        "active": True,
        "currency": "eur",
        "lookup_key": "pumpkit_top_up",
        "recurring": None,
        "type": "one_time",
        "unit_amount": 1000,
    }
    gateway, http = _recorded_gateway(json.dumps({"object": "list", "data": [one_off]}))

    assert await gateway.get_one_off_price("pumpkit_top_up") == OneOffPrice(
        key="pumpkit_top_up", price_id="price_1TopUp", amount=1000, currency="eur"
    )
    query = parse_qs(urlsplit(http.urls[0]).query)
    assert query["lookup_keys[0]"] == ["pumpkit_top_up"]

    recurring = {**one_off, "type": "recurring", "recurring": {"interval": "month"}}
    gateway, _ = _recorded_gateway(json.dumps({"object": "list", "data": [recurring]}))
    assert await gateway.get_one_off_price("pumpkit_top_up") is None


async def test_a_one_off_price_without_its_lookup_key_is_no_top_up():
    # The dev stack's Stripe Emulator ignores the lookup_keys filter and leaves the field out.
    unkeyed = {
        "id": "price_top_up",
        "object": "price",
        "active": True,
        "currency": "eur",
        "type": "one_time",
        "unit_amount": 500,
    }
    gateway, _ = _recorded_gateway(json.dumps({"object": "list", "data": [unkeyed]}))

    assert await gateway.get_one_off_price("pumpkit_top_up") is None


async def test_the_stripe_top_up_checkout_takes_one_payment_marked_as_a_top_up():
    gateway, http = _recorded_gateway(
        '{"id": "cs_1", "object": "checkout.session", "url": "https://checkout.stripe.com/c/cs_1"}'
    )

    await gateway.create_top_up_checkout(
        customer_id="cus_1", price_id="price_1TopUp", user_id="user_1"
    )

    [form] = http.forms
    assert form["mode"] == ["payment"]
    assert form["line_items[0][price]"] == ["price_1TopUp"]
    assert form["line_items[0][quantity]"] == ["1"]
    assert form["metadata[pumpkit_purchase]"] == ["top_up"]
    assert form["success_url"] == ["http://localhost:5173/billing/top-up/success"]
    assert form["automatic_tax[enabled]"] == ["true"]
    assert form["managed_payments[enabled]"] == ["false"]


async def test_the_stripe_adapter_finds_the_customer_of_a_charge():
    gateway, http = _recorded_gateway(
        '{"id": "ch_1", "object": "charge", "customer": "cus_Contract"}'
    )

    assert await gateway.get_charge_customer(charge_id="ch_1") == "cus_Contract"
    assert urlsplit(http.urls[0]).path == "/v1/charges/ch_1"


@pytest.mark.parametrize(
    ("api_url", "called"),
    [
        (None, "https://api.stripe.com/v1/customers"),
        ("http://emulate:4001", "http://emulate:4001/v1/customers"),
    ],
)
async def test_the_stripe_adapter_calls_stripe_api_url_when_one_is_set(
    monkeypatch, api_url, called
):
    monkeypatch.setattr(settings, "STRIPE_API_URL", api_url)
    http = _RecordedStripe('{"id": "cus_e2e", "object": "customer"}')
    gateway = StripeBillingGateway(stripe_client(http_client=http))

    customer_id = await gateway.create_customer(
        email="test@example.com", name="Test", user_id="u1", idempotency_key="k1"
    )

    assert customer_id == "cus_e2e"
    assert http.urls == [called]


async def test_subscription_reads_pending_changes_and_expanded_invoice_settlement():
    listing = json.loads((FIXTURES / "stripe_subscription_list.json").read_text())
    subscription = listing["data"][0]
    subscription.update(
        pending_update={"expires_at": 1762387200},
        schedule={"id": "sub_sched_contract"},
        latest_invoice={"id": "in_contract", "status": "open"},
    )
    listing["data"] = [subscription]
    http = _RecordedStripe(json.dumps(listing))
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))

    [result] = await gateway.list_subscriptions(customer_id="cus_Contract")

    assert result.has_pending_update is True
    assert result.schedule_id == "sub_sched_contract"
    assert result.latest_invoice_status == "open"
    assert parse_qs(urlsplit(http.urls[0]).query)["expand[0]"] == ["data.latest_invoice"]


@pytest.mark.parametrize(
    "invoice_status, unsettled",
    [
        ("paid", False),
        ("void", False),
        ("open", True),
        ("uncollectible", True),
        ("draft", True),
        (None, True),
    ],
)
async def test_customer_invoice_settlement_reads_all_invoices_not_only_the_latest(
    invoice_status, unsettled
):
    body = json.dumps(
        {
            "object": "list",
            "url": "/v1/invoices",
            "has_more": False,
            "data": [
                {"id": "in_older", "object": "invoice", "status": invoice_status},
                {"id": "in_latest", "object": "invoice", "status": "paid"},
            ],
        }
    )
    http = _RecordedStripe(body)
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))
    assert await gateway.has_unsettled_invoices(customer_id="cus_Contract") is unsettled
    assert parse_qs(urlsplit(http.urls[0]).query)["customer"] == ["cus_Contract"]


@pytest.mark.parametrize("mode,pending", [("subscription", True), ("payment", False)])
async def test_pending_subscription_checkout_read_is_customer_scoped_and_does_not_expire(
    mode, pending
):
    gateway, http = _recorded_gateway(
        json.dumps(
            {
                "object": "list",
                "url": "/v1/checkout/sessions",
                "has_more": False,
                "data": [
                    {
                        "id": "cs_pending",
                        "object": "checkout.session",
                        "mode": mode,
                        "status": "open",
                    }
                ],
            }
        )
    )
    assert await gateway.has_open_subscription_checkout(customer_id="cus_Contract") is pending
    assert len(http.urls) == 1
    assert parse_qs(urlsplit(http.urls[0]).query)["customer"] == ["cus_Contract"]
    assert parse_qs(urlsplit(http.urls[0]).query)["status"] == ["open"]


def _setup_checkout(intent_status: str) -> dict:
    return {
        "mode": "setup",
        "status": "complete",
        "setup_intent": {"id": "seti_check", "object": "setup_intent", "status": intent_status},
    }


@pytest.mark.parametrize(
    "state,pending",
    [
        ({"mode": "payment", "status": "open", "payment_status": "unpaid"}, True),
        ({"mode": "payment", "status": "complete", "payment_status": "unpaid"}, True),
        ({"mode": "payment", "status": "complete", "payment_status": "paid"}, False),
        (
            {
                "mode": "payment",
                "status": "complete",
                "payment_status": "unpaid",
                "payment_intent": {
                    "id": "pi_check",
                    "object": "payment_intent",
                    "status": "canceled",
                },
            },
            False,
        ),
        (
            {
                "mode": "payment",
                "status": "complete",
                "payment_status": "unpaid",
                "payment_intent": {
                    "id": "pi_check",
                    "object": "payment_intent",
                    "status": "processing",
                },
            },
            True,
        ),
        (
            {
                "mode": "payment",
                "status": "complete",
                "payment_status": "unpaid",
                "payment_intent": {
                    "id": "pi_check",
                    "object": "payment_intent",
                    "status": "requires_payment_method",
                },
            },
            True,
        ),
        (
            {"mode": "subscription", "status": "complete", "payment_status": "no_payment_required"},
            False,
        ),
        ({"mode": "payment", "status": "expired", "payment_status": "unpaid"}, False),
        # The old paid signup flow left setup Checkouts, finished by their SetupIntent.
        (_setup_checkout("succeeded"), False),
        (_setup_checkout("canceled"), False),
        (_setup_checkout("requires_action"), True),
        ({"mode": "setup", "status": "open"}, True),
        ({"mode": "payment", "status": "complete"}, True),
        ({"mode": "payment", "payment_status": "paid"}, True),
        ({"status": "complete", "payment_status": "paid"}, True),
        (
            {
                "mode": "subscription",
                "status": "complete",
                "payment_status": "unpaid",
                "payment_intent": {
                    "id": "pi_check",
                    "object": "payment_intent",
                    "status": "canceled",
                },
            },
            False,
        ),
    ],
)
async def test_pending_checkout_read_includes_async_payment_and_fails_closed(state, pending):
    gateway, http = _recorded_gateway(
        json.dumps(
            {
                "object": "list",
                "url": "/v1/checkout/sessions",
                "has_more": False,
                "data": [{"id": "cs_check", "object": "checkout.session", **state}],
            }
        )
    )
    assert await gateway.has_pending_checkout(customer_id="cus_Contract") is pending
    assert len(http.urls) == 1
    query = parse_qs(urlsplit(http.urls[0]).query)
    assert query["customer"] == ["cus_Contract"]
    assert "status" not in query
    expanded = {
        value for key, values in query.items() if key.startswith("expand") for value in values
    }
    assert expanded == {"data.payment_intent", "data.setup_intent"}


async def test_coupon_deferral_sends_absolute_target_without_proration_and_stable_identity():
    http = _RecordedStripe('{"id":"sub_defer","object":"subscription"}')
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))
    target = datetime(2028, 3, 31, 12, tzinfo=timezone.utc)
    await gateway.defer_renewal(
        subscription_id="sub_defer", target=target, operation_id="operation_123"
    )
    assert http.methods == ["post"]
    assert http.urls[0].endswith("/v1/subscriptions/sub_defer")
    assert http.forms[0] == {
        "trial_end": ["1838116800"],
        "proration_behavior": ["none"],
        "metadata[pumpkit_coupon_operation]": ["operation_123"],
    }
    assert http.headers[0]["Idempotency-Key"] == "coupon-deferral-operation_123"


@pytest.mark.parametrize("interval, period_end", [("month", 1762387200), ("year", 1791244800)])
@pytest.mark.parametrize("paid, expected", [(1900, True), (0, False)])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_settlement_facts_distinguish_paid_coverage_from_coupon_zero_invoice(
    paid, expected, interval, period_end, cancelled
):
    raw = json.loads((FIXTURES / "stripe_subscription_list.json").read_text())
    state = raw["data"][0]
    state["status"] = "active"
    state["items"]["data"][0]["price"]["recurring"]["interval"] = interval
    state["items"]["data"][0]["current_period_end"] = period_end
    state["cancel_at_period_end"] = cancelled
    state["billing_mode"] = {"type": "classic"}
    state["latest_invoice"] = {
        "id": "in_paid",
        "status": "paid",
        "amount_paid": paid,
        "amount_remaining": 0,
        "lines": {
            "data": [
                {
                    "amount": paid,
                    "parent": {"subscription_item_details": {"subscription_item": "si_1QaRunning"}},
                    "period": {"start": 1759708800, "end": period_end},
                }
            ]
        },
    }
    http = _RecordedStripe(json.dumps(raw))
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))
    result = (await gateway.list_subscriptions(customer_id="cus_Contract"))[0]
    assert result.interval == interval
    assert result.current_period_end == datetime.fromtimestamp(period_end, tz=timezone.utc)
    assert result.paid_current_period is expected
    assert result.cancel_at == (
        datetime.fromtimestamp(period_end, tz=timezone.utc) if cancelled else None
    )
    assert result.billing_mode == "classic"
    assert result.item_id == "si_1QaRunning"


@pytest.mark.parametrize("status", [400, 500])
async def test_deferral_error_classifies_definite_refusal_and_ambiguous_provider_failure(status):
    class RejectedStripe(_RecordedStripe):
        def request(self, method, url, headers, post_data=None, *, _usage=None):
            return (
                json.dumps(
                    {
                        "error": {
                            "type": "invalid_request_error" if status == 400 else "api_error",
                            "message": "Provider detail",
                        }
                    }
                ),
                status,
                {},
            )

    http = RejectedStripe("{}")
    gateway = StripeBillingGateway(
        stripe.StripeClient("sk_test_contract", http_client=http, max_network_retries=0)
    )
    with pytest.raises(BillingProviderError) as caught:
        await gateway.defer_renewal(
            subscription_id="sub_defer",
            target=datetime(2028, 3, 31, 12, tzinfo=timezone.utc),
            operation_id="classify_deferral",
        )
    assert isinstance(caught.value, DeferralRefused) is (status == 400)


_ARRANGED_CHECKOUT = json.dumps(
    {
        "id": "cs_arranged",
        "object": "checkout.session",
        "mode": "subscription",
        "status": "open",
        "customer": "cus_Contract",
        "metadata": {"pumpkit_paid_signup": "paid_signup_contract"},
        "url": "https://checkout.test/arranged",
    }
)


async def _arrange(gateway: StripeBillingGateway):
    return await gateway.create_paid_signup_checkout(
        customer_id="cus_Contract",
        user_id="user_contract",
        operation_id="paid_signup_contract",
        price_id="price_monthly",
        first_payment_at=datetime(2028, 1, 31, 9, 30, tzinfo=timezone.utc),
        expires_at=datetime(2027, 12, 1, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize("managed", [False, True], ids=["seller", "managed-payments"])
async def test_an_arranged_signup_checkout_sends_the_plan_trial_end_metadata_and_seller_settings(
    monkeypatch, managed
):
    monkeypatch.setattr(settings, "STRIPE_MANAGED_PAYMENTS", managed)
    gateway, http = _recorded_gateway(_ARRANGED_CHECKOUT)

    checkout = await _arrange(gateway)

    assert checkout.id == "cs_arranged"
    assert checkout.status == "open"
    assert checkout.url == "https://checkout.test/arranged"
    [form] = http.forms
    assert form["mode"] == ["subscription"]
    assert form["customer"] == ["cus_Contract"]
    assert form["client_reference_id"] == ["user_contract"]
    assert form["line_items[0][price]"] == ["price_monthly"]
    assert form["line_items[0][quantity]"] == ["1"]
    assert form["subscription_data[trial_end]"] == ["1832923800"]
    assert form["subscription_data[metadata][pumpkit_paid_signup]"] == ["paid_signup_contract"]
    assert form["metadata[pumpkit_paid_signup]"] == ["paid_signup_contract"]
    assert form["expires_at"] == ["1827619200"]
    assert form["success_url"] == [settings.billing_page_url()]
    assert form["cancel_url"] == [settings.billing_page_url()]
    assert "subscription_data[trial_period_days]" not in form
    assert "allow_promotion_codes" not in form
    assert not [key for key in form if key.startswith(("payment_method_types", "setup_intent"))]
    assert http.headers[0]["Idempotency-Key"] == "paid_signup_contract:checkout"
    if managed:
        assert form["managed_payments[enabled]"] == ["true"]
        assert not [key for key in form if key.startswith(_SELLER_ONLY_PARAMS)]
    else:
        assert form["managed_payments[enabled]"] == ["false"]
        assert form["automatic_tax[enabled]"] == ["true"]
        assert form["tax_id_collection[enabled]"] == ["true"]


async def test_arranged_subscription_checkouts_are_read_back_with_their_subscription():
    arranged = {
        "id": "cs_arranged",
        "object": "checkout.session",
        "mode": "subscription",
        "status": "complete",
        "customer": "cus_Contract",
        "metadata": {"pumpkit_paid_signup": "paid_signup_contract"},
        "subscription": "sub_arranged",
        "url": None,
    }
    ordinary = {
        "id": "cs_ordinary",
        "object": "checkout.session",
        "mode": "subscription",
        "status": "open",
        "customer": "cus_Contract",
        "metadata": {},
    }
    gateway, http = _recorded_gateway(
        json.dumps({"object": "list", "data": [ordinary, arranged], "has_more": False})
    )

    checkouts = await gateway.list_paid_signup_checkouts(customer_id="cus_Contract")

    assert [(c.id, c.operation_id, c.status, c.subscription_id) for c in checkouts] == [
        ("cs_arranged", "paid_signup_contract", "complete", "sub_arranged")
    ]


async def test_interval_change_retains_trial_anchor_and_cancellation_without_proration():
    http = _RecordedStripe('{"id":"sub_change","object":"subscription"}')
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))
    await gateway.change_plan(
        subscription_id="sub_change",
        item_id="si_change",
        price_id="price_year",
        operation_id="change_contract",
        first_payment_at=datetime(2028, 1, 31, tzinfo=timezone.utc),
    )
    assert http.forms[0] == {
        "items[0][id]": ["si_change"],
        "items[0][price]": ["price_year"],
        "proration_behavior": ["none"],
        "trial_end": ["1832889600"],
        "metadata[pumpkit_plan_change]": ["change_contract"],
    }
    assert http.headers[0]["Idempotency-Key"] == "plan-change-change_contract"


@pytest.mark.parametrize(
    "unsafe",
    [None, "subscription_update", "subscription_cancel", "login_page", "inactive", "missing"],
)
async def test_management_portal_requires_explicit_current_restricted_configuration(
    monkeypatch, unsafe
):
    configuration = {
        "id": "bpc_safe",
        "object": "billing_portal.configuration",
        "active": True,
        "features": {
            "subscription_update": {"enabled": False},
            "subscription_cancel": {"enabled": False},
        },
        "login_page": {"enabled": False},
    }
    if unsafe in {"subscription_update", "subscription_cancel"}:
        configuration["features"][unsafe]["enabled"] = True
    elif unsafe == "login_page":
        configuration["login_page"]["enabled"] = True
    elif unsafe == "inactive":
        configuration["active"] = False
    elif unsafe == "missing":
        configuration["features"] = {}

    class PortalStripe(_RecordedStripe):
        def request(self, method, url, headers, post_data=None, *, _usage=None):
            self._bodies = [
                json.dumps(
                    configuration
                    if method == "get"
                    else {
                        "id": "bps_safe",
                        "object": "billing_portal.session",
                        "url": "https://billing.test/safe",
                    }
                )
            ]
            return super().request(method, url, headers, post_data, _usage=_usage)

    monkeypatch.setattr(settings, "STRIPE_COUPON_PORTAL_CONFIGURATION_ID", "bpc_safe")
    http = PortalStripe("{}")
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))
    if unsafe:
        with pytest.raises(BillingProviderError):
            await gateway.create_portal_url(customer_id="cus_contract", restricted=True)
        assert http.methods == ["get"]
    else:
        assert (
            await gateway.create_portal_url(customer_id="cus_contract", restricted=True)
            == "https://billing.test/safe"
        )
        assert http.methods == ["get", "post"]
        assert http.forms[-1]["configuration"] == ["bpc_safe"]


@pytest.mark.parametrize("status", [400, 409])
async def test_interval_change_in_progress_key_is_uncertain_even_on_invalid_request(status):
    class InProgressStripe(_RecordedStripe):
        def request(self, method, url, headers, post_data=None, *, _usage=None):
            return (
                json.dumps(
                    {
                        "error": {
                            "type": "invalid_request_error",
                            "code": "idempotency_key_in_use",
                            "message": "The original request is still executing",
                        }
                    }
                ),
                status,
                {},
            )

    http = InProgressStripe("{}")
    gateway = StripeBillingGateway(
        stripe.StripeClient("sk_test_contract", http_client=http, max_network_retries=0)
    )
    with pytest.raises(BillingProviderError) as caught:
        await gateway.change_plan(
            subscription_id="sub_change",
            item_id="si_change",
            price_id="price_year",
            operation_id="change_in_progress",
        )
    assert not isinstance(caught.value, DeferralRefused)


async def test_in_progress_coupon_deferral_is_uncertain():
    class InProgressStripe(_RecordedStripe):
        def request(self, method, url, headers, post_data=None, *, _usage=None):
            return (
                json.dumps(
                    {
                        "error": {
                            "type": "invalid_request_error",
                            "code": "idempotency_key_in_use",
                            "message": "Still running",
                        }
                    }
                ),
                400,
                {},
            )

    gateway = StripeBillingGateway(
        stripe.StripeClient(
            "sk_test_contract", http_client=InProgressStripe("{}"), max_network_retries=0
        )
    )
    with pytest.raises(BillingProviderError) as caught:
        await gateway.defer_renewal(
            subscription_id="sub_defer",
            target=datetime(2028, 3, 31, 12, tzinfo=timezone.utc),
            operation_id="in_progress",
        )
    assert not isinstance(caught.value, DeferralRefused)


async def test_legacy_interval_change_replays_original_anchor_parameter():
    http = _RecordedStripe('{"id":"sub_change","object":"subscription"}')
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))
    await gateway.change_plan(
        subscription_id="sub_change",
        item_id="si_change",
        price_id="price_month",
        operation_id="legacy_change",
    )
    assert http.forms[0]["billing_cycle_anchor"] == ["unchanged"]
    assert http.headers[0]["Idempotency-Key"] == "plan-change-legacy_change"
