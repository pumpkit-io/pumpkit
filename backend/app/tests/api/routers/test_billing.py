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
