from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import app.api.mediators.purchases as purchases_mediator
import app.core.exceptions as exceptions_module
from app.core.purchases import PRODUCTS


async def test_list_products(client):
    response = await client.get("/api/v1/billing/products")
    assert response.status_code == 200
    ids = [p["id"] for p in response.json()["data"]]
    assert ids == [p.id for p in PRODUCTS]


async def test_checkout_and_list_purchases(client, monkeypatch):
    monkeypatch.setattr(
        purchases_mediator.stripe.checkout.Session,
        "create",
        lambda **params: SimpleNamespace(id="cs_router", url="https://checkout.stripe.test/x"),
    )
    monkeypatch.setattr(
        purchases_mediator.stripe_customers_service,
        "ensure_stripe_customer",
        AsyncMock(return_value="cus_1"),
    )
    response = await client.post(
        "/api/v1/billing/purchases/checkout", json={"product_id": PRODUCTS[0].id}
    )
    assert response.status_code == 200
    assert response.json() == {"url": "https://checkout.stripe.test/x", "session_id": "cs_router"}

    response = await client.get("/api/v1/billing/purchases")
    assert response.status_code == 200
    rows = response.json()["data"]
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
    assert rows[0]["product_id"] == PRODUCTS[0].id


async def test_checkout_unknown_product_is_400(client):
    response = await client.post("/api/v1/billing/purchases/checkout", json={"product_id": "nope"})
    assert response.status_code == 400
    assert "product_id must be one of" in response.json()["detail"]


async def test_unexpected_checkout_failure_returns_500_with_captured_error_id(client, monkeypatch):
    monkeypatch.setattr(
        purchases_mediator,
        "create_checkout_session",
        AsyncMock(side_effect=RuntimeError("stripe exploded")),
    )
    fake_posthog = MagicMock()
    monkeypatch.setattr(exceptions_module, "posthog_client", fake_posthog)

    response = await client.post(
        "/api/v1/billing/purchases/checkout", json={"product_id": PRODUCTS[0].id}
    )

    assert response.status_code == 500
    error_id = response.json()["error_id"]
    fake_posthog.capture_exception.assert_called_once()
    assert fake_posthog.capture_exception.call_args.kwargs["properties"]["error_id"] == error_id
