import json
from typing import Any

import app.api.mediators.stripe as stripe_mediator


def webhook_payload(event_id: str, event_type: str, data_object: dict[str, Any]) -> bytes:
    return json.dumps(
        {"id": event_id, "type": event_type, "data": {"object": data_object}}
    ).encode()


def patch_construct_event(monkeypatch) -> None:
    """Skip signature verification: return the parsed payload like Stripe would."""

    def _construct_event(payload, sig_header, secret):
        return json.loads(payload)

    monkeypatch.setattr(stripe_mediator.stripe.Webhook, "construct_event", _construct_event)
