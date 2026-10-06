"""
The webhook-verification contract both adapters share: the fake signs events
the way Stripe does, so the Stripe adapter must accept them with the same
secret. No network: verification is local HMAC work. The Stripe adapter's
translation of Stripe's answers is checked against recorded Stripe responses.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

import pytest
import stripe

from app.core.billing_gateway import (
    BillingGateway,
    FakeBillingGateway,
    StripeBillingGateway,
    SubscriptionState,
    WebhookEvent,
    WebhookSignatureError,
)
from app.core.config import settings

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

    def request(self, method, url, headers, post_data=None, *, _usage=None):
        self.urls.append(url)
        self.methods.append(method)
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
        ),
        SubscriptionState(
            id="sub_1QaEnded",
            status="canceled",
            price_id="price_1Legacy",
            plan_key=None,
            current_period_end=datetime(2025, 9, 1, tzinfo=timezone.utc),
            cancel_at_period_end=False,
            created_at=datetime(2025, 8, 1, tzinfo=timezone.utc),
        ),
    ]
    [url] = http.urls
    query = parse_qs(urlsplit(url).query)
    # Stripe leaves cancelled Subscriptions out unless asked for all of them.
    assert query["status"] == ["all"]
    assert query["customer"] == ["cus_Contract"]


async def test_the_stripe_adapter_cancels_a_subscription_now():
    http = _RecordedStripe(
        '{"id": "sub_1Incomplete", "object": "subscription", "status": "canceled"}'
    )
    gateway = StripeBillingGateway(stripe.StripeClient("sk_test_contract", http_client=http))

    await gateway.cancel_subscription(subscription_id="sub_1Incomplete")

    assert http.methods == ["delete"]
    assert urlsplit(http.urls[0]).path == "/v1/subscriptions/sub_1Incomplete"


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
