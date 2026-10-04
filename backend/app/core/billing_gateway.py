"""
The `BillingGateway` port: every call Pumpkit makes to its billing provider.

Mediators depend on the port through `get_billing_gateway`; nothing else talks
to Stripe. Inputs and outputs are plain data, so no SDK object leaks out, and
the port never touches the database: persisting what it returns is the
mediator's job. Any provider failure is a `BillingProviderError`, which the
global error handler turns into a 502 with an `error_id`. A webhook that fails
verification is a `WebhookSignatureError` instead: the sender's fault, not the
provider's.

`StripeBillingGateway` is the production adapter and the only module code that
uses the Stripe SDK. `FakeBillingGateway` records calls, returns configured
results, can be told to fail, and signs webhook payloads its own verifier
accepts (tests override the dependency with it).
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import stripe

from app.core.config import settings


class BillingProviderError(Exception):
    """The billing provider failed or answered with something unusable."""


class WebhookSignatureError(Exception):
    """A webhook payload is malformed or its signature doesn't verify."""


@dataclass(frozen=True)
class WebhookEvent:
    """A verified webhook event: its ID, its type and the object it is about."""

    id: str
    type: str
    data_object: dict[str, Any]


class BillingGateway(Protocol):
    def verify_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent:
        """Verify a webhook payload and its signature, or raise `WebhookSignatureError`."""
        ...


def _webhook_event(event: dict[str, Any]) -> WebhookEvent:
    try:
        return WebhookEvent(
            id=event["id"], type=event["type"], data_object=dict(event["data"]["object"])
        )
    except (KeyError, TypeError) as error:
        raise WebhookSignatureError("Webhook payload is not an event") from error


class StripeBillingGateway:
    """Calls Stripe with its own client and API key, off the event loop, and returns plain data."""

    def __init__(self) -> None:
        self._client = stripe.StripeClient(settings.STRIPE_SECRET_KEY)

    def verify_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent:
        # Pure HMAC work, no network: no need to leave the event loop.
        try:
            event = self._client.construct_event(
                payload=payload, sig_header=signature, secret=settings.STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.SignatureVerificationError) as error:
            raise WebhookSignatureError("Invalid Stripe webhook") from error
        return _webhook_event(event.to_dict())


class FakeBillingGateway:
    """
    A billing provider in memory. Sign events with `signed_event`; its
    `verify_webhook` accepts only payloads signed with the same secret.
    """

    def __init__(self, webhook_secret: str = "whsec_fake") -> None:
        self.webhook_secret = webhook_secret

    def signed_event(
        self, *, event_id: str, event_type: str, data_object: dict[str, Any]
    ) -> tuple[bytes, str]:
        """A webhook payload and the signature header the provider would send with it."""
        payload = json.dumps(
            {"id": event_id, "type": event_type, "data": {"object": data_object}}
        ).encode()
        timestamp = str(int(time.time()))
        return payload, f"t={timestamp},v1={self._sign(timestamp, payload)}"

    def verify_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent:
        parts = dict(part.split("=", 1) for part in signature.split(",") if "=" in part)
        timestamp, received = parts.get("t"), parts.get("v1")
        if not timestamp or not received:
            raise WebhookSignatureError("Signature header is incomplete")
        if not hmac.compare_digest(received, self._sign(timestamp, payload)):
            raise WebhookSignatureError("Signature doesn't match the payload")
        try:
            event = json.loads(payload)
        except ValueError as error:
            raise WebhookSignatureError("Payload is not JSON") from error
        return _webhook_event(event)

    def _sign(self, timestamp: str, payload: bytes) -> str:
        signed = f"{timestamp}.".encode() + payload
        return hmac.new(self.webhook_secret.encode(), signed, hashlib.sha256).hexdigest()


@lru_cache
def get_billing_gateway() -> BillingGateway:
    """FastAPI dependency for the `BillingGateway` port."""
    return StripeBillingGateway()
