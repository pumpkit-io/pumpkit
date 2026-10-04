from unittest.mock import AsyncMock

import app.api.mediators.stripe as stripe_mediator


async def test_unexpected_checkout_failure_returns_500_with_captured_error_id(
    client, monkeypatch, assert_reported_500
):
    monkeypatch.setattr(
        stripe_mediator,
        "create_checkout_session",
        AsyncMock(side_effect=RuntimeError("stripe exploded")),
    )

    response = await client.post("/api/v1/stripe/checkout", json={"price_id": "price_123"})

    assert_reported_500(response)


async def test_billing_api_serves_only_subscription_routes(client):
    """Pumpkit bills only by Subscription (ADR 0003): no other billing routes exist."""
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    billing_paths = {
        path
        for path in response.json()["paths"]
        if path.startswith(("/api/v1/billing", "/api/v1/stripe"))
    }
    assert billing_paths == {
        "/api/v1/stripe/me",
        "/api/v1/stripe/prices",
        "/api/v1/stripe/checkout",
        "/api/v1/stripe/billing-portal",
        "/api/v1/stripe/trial",
        "/api/v1/stripe/webhook",
    }
