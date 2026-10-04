import pytest

from app.core.billing_gateway import CheckoutCall, CustomerCall, Plan
from app.core.config import settings
from app.db.models import Subscription

CHECKOUT = "/api/v1/stripe/checkout"
CHECKOUT_MONTHLY = {"plan_key": "pumpkit_pro_monthly"}
PORTAL = "/api/v1/stripe/billing-portal"
PLANS = "/api/v1/stripe/plans"

MONTHLY = Plan(
    key="pumpkit_pro_monthly",
    price_id="price_monthly",
    product_name="Pumpkit Pro",
    amount=900,
    currency="eur",
    interval="month",
    interval_count=1,
)
YEARLY = Plan(
    key="pumpkit_pro_yearly",
    price_id="price_yearly",
    product_name="Pumpkit Pro",
    amount=9000,
    currency="eur",
    interval="year",
    interval_count=1,
)
STRAY = Plan(
    key="stray_test_price",
    price_id="price_stray",
    product_name="Test product",
    amount=1,
    currency="eur",
    interval="month",
    interval_count=1,
)


@pytest.fixture(autouse=True)
def monthly_plan(fake_billing):
    """The test settings sell `pumpkit_pro_monthly`; the fake resolves it."""
    fake_billing.plans = [MONTHLY]


async def test_checkout_by_plan_key_creates_a_checkout_for_one_unit_of_that_plans_price(
    client, db, fake_billing, user
):
    response = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)

    assert response.status_code == 200
    assert response.json() == {"url": fake_billing.checkout_url, "session_id": "cs_fake_1"}
    assert fake_billing.customers_created == [
        CustomerCall(email="alice@example.com", name="Alice", user_id=user.id)
    ]
    assert fake_billing.checkouts == [
        CheckoutCall(
            customer_id="cus_fake_1",
            price_id="price_monthly",
            quantity=1,
            user_id=user.id,
            trial_period_days=14,
        )
    ]
    await db.refresh(user)
    assert user.stripe_customer_id == "cus_fake_1"


async def test_checkout_for_a_user_who_never_had_a_subscription_includes_the_trial(
    client, fake_billing
):
    """The test settings configure a 14-day Trial."""
    response = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)

    assert response.status_code == 200
    assert [c.trial_period_days for c in fake_billing.checkouts] == [14]


async def test_checkout_for_a_user_who_has_had_a_subscription_includes_no_trial(
    client, db, fake_billing, user
):
    db.add(
        Subscription(
            user_id=user.id,
            stripe_subscription_id="sub_old",
            stripe_customer_id="cus_old",
            status="canceled",
        )
    )
    await db.commit()

    response = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)

    assert response.status_code == 200
    assert [c.trial_period_days for c in fake_billing.checkouts] == [None]


async def test_a_trial_length_of_zero_turns_trials_off(client, fake_billing, monkeypatch):
    monkeypatch.setattr(settings, "BILLING_TRIAL_PERIOD_DAYS", 0)

    response = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)

    assert response.status_code == 200
    assert [c.trial_period_days for c in fake_billing.checkouts] == [None]


async def test_checkout_with_an_unknown_plan_key_returns_400_without_calling_the_gateway(
    client, db, fake_billing, user
):
    fake_billing.plans = [MONTHLY, STRAY]

    response = await client.post(CHECKOUT, json={"plan_key": "stray_test_price"})

    assert response.status_code == 400
    assert fake_billing.plan_lookups == []
    assert fake_billing.customers_created == []
    assert fake_billing.checkouts == []
    await db.refresh(user)
    assert user.stripe_customer_id is None


@pytest.mark.parametrize(
    "smuggled",
    [
        {"price_id": "price_stray"},
        {"quantity": 5},
        {"trial_period_days": 365},
    ],
    ids=["price", "quantity", "trial-length"],
)
async def test_a_checkout_payload_cannot_set_the_price_quantity_or_trial(
    client, fake_billing, smuggled
):
    response = await client.post(CHECKOUT, json={**CHECKOUT_MONTHLY, **smuggled})

    assert response.status_code == 422
    assert fake_billing.customers_created == []
    assert fake_billing.checkouts == []


async def test_checkout_without_a_plan_key_is_rejected(client, fake_billing):
    response = await client.post(CHECKOUT, json={"price_id": "price_monthly"})

    assert response.status_code == 422
    assert fake_billing.checkouts == []


async def test_a_configured_plan_the_provider_cannot_resolve_fails_checkout_with_502(
    client, fake_billing, assert_reported_502
):
    fake_billing.plans = []

    response = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)

    assert_reported_502(response)
    assert fake_billing.customers_created == []
    assert fake_billing.checkouts == []


async def test_a_gateway_failure_on_checkout_returns_502_with_error_id(
    client, fake_billing, assert_reported_502
):
    fake_billing.fail_on = {"create_subscription_checkout"}

    response = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)

    assert_reported_502(response)


async def test_a_failed_checkout_keeps_the_new_customer_and_a_retry_reuses_it(
    client, db, fake_billing, user
):
    fake_billing.fail_on = {"create_subscription_checkout"}
    failed = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)
    assert failed.status_code == 502

    await db.refresh(user)
    assert user.stripe_customer_id == "cus_fake_1"

    fake_billing.fail_on = set()
    retried = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)

    assert retried.status_code == 200
    assert len(fake_billing.customers_created) == 1
    assert [call.customer_id for call in fake_billing.checkouts] == ["cus_fake_1"]


async def test_a_gateway_failure_creating_the_customer_returns_502_and_saves_nothing(
    client, db, fake_billing, user, assert_reported_502
):
    fake_billing.fail_on = {"create_customer"}

    response = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)

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


async def test_the_plans_endpoint_returns_only_the_configured_plans(
    client, fake_billing, monkeypatch
):
    monkeypatch.setattr(
        settings, "BILLING_PLAN_KEYS", ["pumpkit_pro_yearly", "pumpkit_pro_monthly"]
    )
    fake_billing.plans = [MONTHLY, STRAY, YEARLY]

    response = await client.get(PLANS)

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "key": "pumpkit_pro_yearly",
                "product_name": "Pumpkit Pro",
                "amount": 9000,
                "currency": "eur",
                "interval": "year",
                "interval_count": 1,
            },
            {
                "key": "pumpkit_pro_monthly",
                "product_name": "Pumpkit Pro",
                "amount": 900,
                "currency": "eur",
                "interval": "month",
                "interval_count": 1,
            },
        ]
    }


async def test_a_configured_plan_the_provider_does_not_know_is_left_out(
    client, fake_billing, monkeypatch
):
    monkeypatch.setattr(settings, "BILLING_PLAN_KEYS", ["pumpkit_pro_monthly", "pumpkit_gone"])
    fake_billing.plans = [MONTHLY]

    response = await client.get(PLANS)

    assert response.status_code == 200
    assert [plan["key"] for plan in response.json()["data"]] == ["pumpkit_pro_monthly"]


async def test_a_gateway_failure_listing_plans_returns_502(
    client, fake_billing, assert_reported_502
):
    fake_billing.fail_on = {"list_plans"}

    response = await client.get(PLANS)

    assert_reported_502(response)


async def test_the_cardless_trial_route_no_longer_exists(client, fake_billing):
    """A Trial comes only through Checkout, with a card (spec #10)."""
    response = await client.post(
        "/api/v1/stripe/trial", json={"price_id": "price_monthly", "trial_period_days": 365}
    )

    assert response.status_code == 404
    assert fake_billing.customers_created == []


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
        "/api/v1/stripe/plans",
        "/api/v1/stripe/checkout",
        "/api/v1/stripe/billing-portal",
        "/api/v1/stripe/webhook",
    }
