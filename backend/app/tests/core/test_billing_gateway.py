"""
The webhook-verification contract both adapters share: the fake signs events
the way Stripe does, so the Stripe adapter must accept them with the same
secret. No network: verification is local HMAC work.
"""

import pytest

from app.core.billing_gateway import (
    BillingGateway,
    FakeBillingGateway,
    StripeBillingGateway,
    WebhookEvent,
    WebhookSignatureError,
)
from app.core.config import settings

SECRET = "whsec_contract"


@pytest.fixture(params=["stripe", "fake"])
def verifier(request, monkeypatch) -> BillingGateway:
    if request.param == "fake":
        return FakeBillingGateway(webhook_secret=SECRET)
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", SECRET)
    return StripeBillingGateway()


def _signed(secret: str = SECRET) -> tuple[bytes, str]:
    return FakeBillingGateway(webhook_secret=secret).signed_event(
        event_id="evt_1",
        event_type="customer.subscription.updated",
        data_object={"id": "sub_1", "items": {"data": [{"price": {"id": "price_1"}}]}},
    )


def test_a_signed_event_verifies_into_plain_data(verifier):
    payload, signature = _signed()

    event = verifier.verify_webhook(payload=payload, signature=signature)

    assert event == WebhookEvent(
        id="evt_1",
        type="customer.subscription.updated",
        data_object={"id": "sub_1", "items": {"data": [{"price": {"id": "price_1"}}]}},
    )
    assert type(event.data_object["items"]) is dict


@pytest.mark.parametrize(
    "tamper",
    [
        lambda payload, signature: (payload, "t=1,v1=deadbeef"),
        lambda payload, signature: (payload, "garbage"),
        lambda payload, signature: (payload.replace(b"price_1", b"price_2"), signature),
        lambda payload, signature: (b"not json", signature),
        lambda payload, signature: _signed("whsec_someone_else"),
    ],
    ids=["wrong-signature", "malformed-header", "tampered-payload", "not-json", "other-secret"],
)
def test_an_unverifiable_event_is_rejected(verifier, tamper):
    payload, signature = tamper(*_signed())

    with pytest.raises(WebhookSignatureError):
        verifier.verify_webhook(payload=payload, signature=signature)
