from sqlalchemy import select

from app.core.billing_gateway import CheckoutCall, CustomerCall, Price
from app.db.models import Subscription

CHECKOUT = "/api/v1/stripe/checkout"
PORTAL = "/api/v1/stripe/billing-portal"


async def test_checkout_creates_the_stripe_customer_and_a_checkout(client, db, fake_billing, user):
    response = await client.post(CHECKOUT, json={"price_id": "price_123"})

    assert response.status_code == 200
    assert response.json() == {"url": fake_billing.checkout_url, "session_id": "cs_fake_1"}
    assert fake_billing.customers_created == [
        CustomerCall(email="alice@example.com", name="Alice", user_id=user.id)
    ]
    assert fake_billing.checkouts == [
        CheckoutCall(
            customer_id="cus_fake_1", price_id="price_123", user_id=user.id, trial_period_days=None
        )
    ]
    await db.refresh(user)
    assert user.stripe_customer_id == "cus_fake_1"


async def test_a_gateway_failure_on_checkout_returns_502_with_error_id(
    client, fake_billing, assert_reported_502
):
    fake_billing.fail_on = {"create_subscription_checkout"}

    response = await client.post(CHECKOUT, json={"price_id": "price_123"})

    assert_reported_502(response)


async def test_a_failed_checkout_keeps_the_new_customer_and_a_retry_reuses_it(
    client, db, fake_billing, user
):
    fake_billing.fail_on = {"create_subscription_checkout"}
    failed = await client.post(CHECKOUT, json={"price_id": "price_123"})
    assert failed.status_code == 502

    await db.refresh(user)
    assert user.stripe_customer_id == "cus_fake_1"

    fake_billing.fail_on = set()
    retried = await client.post(CHECKOUT, json={"price_id": "price_123"})

    assert retried.status_code == 200
    assert len(fake_billing.customers_created) == 1
    assert [call.customer_id for call in fake_billing.checkouts] == ["cus_fake_1"]


async def test_a_gateway_failure_creating_the_customer_returns_502_and_saves_nothing(
    client, db, fake_billing, user, assert_reported_502
):
    fake_billing.fail_on = {"create_customer"}

    response = await client.post(CHECKOUT, json={"price_id": "price_123"})

    assert_reported_502(response)
    assert fake_billing.checkouts == []
    await db.refresh(user)
    assert user.stripe_customer_id is None


async def test_the_portal_endpoint_returns_the_gateway_url(client, db, fake_billing, user):
    user.stripe_customer_id = "cus_existing"
    await db.commit()
    fake_billing.portal_url = "https://billing.test/portal/abc"

    response = await client.post(PORTAL)

    assert response.status_code == 200
    assert response.json() == {"url": "https://billing.test/portal/abc"}
    assert fake_billing.portals == ["cus_existing"]
    assert fake_billing.customers_created == []


async def test_the_portal_creates_the_stripe_customer_when_missing(client, db, fake_billing, user):
    response = await client.post(PORTAL)

    assert response.status_code == 200
    assert fake_billing.portals == ["cus_fake_1"]
    await db.refresh(user)
    assert user.stripe_customer_id == "cus_fake_1"


async def test_prices_come_from_the_gateway(client, fake_billing):
    fake_billing.prices = [
        Price(
            id="price_1",
            currency="usd",
            unit_amount=500,
            interval="month",
            interval_count=1,
            product_id="prod_1",
            product_name="Pro",
            product_description="d",
        ),
        Price(id="price_once", currency="usd", unit_amount=900),
    ]

    response = await client.get("/api/v1/stripe/prices")

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "id": "price_1",
                "currency": "usd",
                "unit_amount": 500,
                "recurring": {"interval": "month", "interval_count": 1},
                "product": {"id": "prod_1", "name": "Pro", "description": "d"},
            },
            {
                "id": "price_once",
                "currency": "usd",
                "unit_amount": 900,
                "recurring": None,
                "product": None,
            },
        ]
    }


async def test_a_gateway_failure_listing_prices_returns_502(
    client, fake_billing, assert_reported_502
):
    fake_billing.fail_on = {"list_prices"}

    response = await client.get("/api/v1/stripe/prices")

    assert_reported_502(response)


async def test_the_trial_endpoint_starts_a_trial_through_the_gateway(
    client, db, fake_billing, user
):
    fake_billing.trial_subscription = {
        "id": "sub_trial",
        "customer": "cus_fake_1",
        "status": "trialing",
        "trial_end": 1_900_000_000,
        "cancel_at_period_end": False,
        "items": {"data": [{"price": {"id": "price_trial"}, "current_period_end": 1_900_000_000}]},
    }

    response = await client.post(
        "/api/v1/stripe/trial", json={"price_id": "price_trial", "trial_period_days": 7}
    )

    assert response.status_code == 200
    assert response.json()["subscription_id"] == "sub_trial"
    assert response.json()["status"] == "trialing"
    assert [(t.customer_id, t.price_id, t.trial_period_days) for t in fake_billing.trials] == [
        ("cus_fake_1", "price_trial", 7)
    ]
    await db.commit()
    sub = (await db.execute(select(Subscription))).scalar_one()
    assert sub.user_id == user.id
    assert sub.stripe_price_id == "price_trial"
    assert sub.current_period_end is not None


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
