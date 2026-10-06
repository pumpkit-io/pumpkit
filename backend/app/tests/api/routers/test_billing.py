from datetime import datetime, timezone

import pytest

import app.api.services.subscriptions as subscriptions_service
from app.core.billing_gateway import (
    CheckoutCall,
    CustomerCall,
    FakeBillingGateway,
    Plan,
    SubscriptionState,
)
from app.core.config import settings
from app.core.subscription_status import SubscriptionStatus

CUSTOMER = "cus_alice"
BILLING_ME = "/api/v1/billing/me"
CHECKOUT = "/api/v1/billing/checkout"
CHECKOUT_MONTHLY = {"plan_key": "pumpkit_pro_monthly"}
PORTAL = "/api/v1/billing/portal"
PLANS = "/api/v1/billing/plans"

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
        CustomerCall(
            email="alice@example.com",
            name="Alice",
            user_id=user.id,
            idempotency_key=f"pumpkit-user-{user.id}-customer",
        )
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


async def _with_customer(db, user, customer_id: str = CUSTOMER) -> None:
    user.stripe_customer_id = customer_id
    await db.commit()


def _subscription(sub_id: str, status: SubscriptionStatus) -> SubscriptionState:
    return SubscriptionState(
        id=sub_id,
        status=status,
        price_id="price_monthly",
        plan_key="pumpkit_pro_monthly",
        current_period_end=datetime(2026, 11, 6, tzinfo=timezone.utc),
        cancel_at_period_end=False,
        created_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize("running_status", ["trialing", "active", "past_due", "unpaid", "paused"])
async def test_checkout_for_a_user_with_a_running_subscription_returns_409(
    client, db, fake_billing, user, running_status
):
    """No webhook has reported it: Checkout asks Stripe itself."""
    await _with_customer(db, user)
    fake_billing.set_subscription(CUSTOMER, _subscription("sub_running", running_status))

    response = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "You already have a Subscription. Manage it in the billing portal."
    )
    assert fake_billing.checkouts == []
    assert fake_billing.cancelled_subscriptions == []


async def test_a_running_subscription_blocks_checkout_even_before_its_customer_is_saved(
    client, fake_billing
):
    """The customer created by this Checkout already has a Subscription in Stripe."""
    fake_billing.set_subscription("cus_fake_1", _subscription("sub_running", "active"))

    response = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)

    assert response.status_code == 409
    assert fake_billing.checkouts == []


async def test_checkout_is_allowed_after_the_subscription_has_ended_without_a_trial(
    client, db, fake_billing, user
):
    """The Ended Subscription is known only to Stripe: it still uses up the Trial."""
    await _with_customer(db, user)
    fake_billing.set_subscription(CUSTOMER, _subscription("sub_old", "canceled"))
    fake_billing.set_subscription(CUSTOMER, _subscription("sub_older", "incomplete_expired"))

    response = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)

    assert response.status_code == 200
    assert fake_billing.checkouts == [
        CheckoutCall(
            customer_id=CUSTOMER,
            price_id="price_monthly",
            quantity=1,
            user_id=user.id,
            trial_period_days=None,
        )
    ]
    assert fake_billing.cancelled_subscriptions == []


async def test_checkout_cancels_the_users_incomplete_subscriptions_first(
    client, db, fake_billing, user
):
    """Only the newest attempt can succeed, so a User can't end up paying twice."""
    await _with_customer(db, user)
    fake_billing.set_subscription(CUSTOMER, _subscription("sub_half_a", "incomplete"))
    fake_billing.set_subscription(CUSTOMER, _subscription("sub_half_b", "incomplete"))
    fake_billing.set_subscription(CUSTOMER, _subscription("sub_old", "canceled"))

    response = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)

    assert response.status_code == 200
    assert sorted(fake_billing.cancelled_subscriptions) == ["sub_half_a", "sub_half_b"]
    assert {s.status for s in await fake_billing.list_subscriptions(customer_id=CUSTOMER)} == {
        "canceled"
    }
    assert [c.trial_period_days for c in fake_billing.checkouts] == [None]


@pytest.mark.parametrize(
    ("status", "expected_code"), [("active", 409), ("canceled", 200)], ids=["refused", "allowed"]
)
async def test_checkout_keeps_what_it_synced_from_stripe(
    client, db, fake_billing, user, status, expected_code
):
    await _with_customer(db, user)
    fake_billing.set_subscription(CUSTOMER, _subscription("sub_1", status))

    response = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)

    assert response.status_code == expected_code
    synced = await subscriptions_service.get_subscription_by_stripe_id(db, "sub_1")
    assert synced is not None
    assert (synced.user_id, synced.status) == (user.id, status)


@pytest.mark.parametrize("failing", ["list_subscriptions", "cancel_subscription"])
async def test_a_gateway_failure_syncing_or_cancelling_returns_502_before_any_checkout(
    client, db, fake_billing, user, failing, assert_reported_502
):
    await _with_customer(db, user)
    fake_billing.set_subscription(CUSTOMER, _subscription("sub_half", "incomplete"))
    fake_billing.fail_on = {failing}

    response = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)

    assert_reported_502(response)
    assert fake_billing.expired_checkouts == []
    assert fake_billing.checkouts == []


async def test_a_new_checkout_expires_the_users_still_open_checkout(client, fake_billing):
    """Otherwise a User could open several Trial Checkouts and complete each one."""
    first = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)
    assert first.status_code == 200
    assert fake_billing.expired_checkouts == []

    second = await client.post(CHECKOUT, json=CHECKOUT_MONTHLY)

    assert second.status_code == 200
    assert second.json()["session_id"] == "cs_fake_2"
    assert fake_billing.expired_checkouts == ["cs_fake_1"]


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


async def _hold(db, user, *states: SubscriptionState) -> None:
    """Make Pumpkit's copy of the User's Subscriptions hold `states`, as a sync would."""
    gateway = FakeBillingGateway()
    for state in states:
        gateway.set_subscription(CUSTOMER, state)
    await subscriptions_service.sync_customer(db, gateway, user_id=user.id, customer_id=CUSTOMER)
    await db.commit()


def _billing_subscription(status: str) -> dict:
    return {
        "status": status,
        "plan_key": "pumpkit_pro_monthly",
        # SQLite drops the time zone that Postgres keeps.
        "current_period_end": "2026-11-06T00:00:00",
        "cancel_at_period_end": False,
    }


async def test_billing_me_for_a_user_with_no_subscription_offers_the_trial(
    client, fake_billing, monkeypatch
):
    monkeypatch.setattr(settings, "BILLING_TRIAL_PERIOD_DAYS", 14)

    response = await client.get(BILLING_ME)

    assert response.status_code == 200
    assert response.json() == {
        "subscription": None,
        "subscribed": False,
        "may_subscribe": True,
        "trial_days": 14,
    }


@pytest.mark.parametrize(
    ("status", "subscribed"),
    [
        ("trialing", True),
        ("active", True),
        ("past_due", True),
        ("unpaid", False),
        ("paused", False),
    ],
)
async def test_billing_me_reports_the_running_subscription_and_offers_nothing(
    client, db, fake_billing, user, status, subscribed
):
    await _hold(db, user, _subscription("sub_old", "canceled"), _subscription("sub_1", status))

    response = await client.get(BILLING_ME)

    assert response.status_code == 200
    assert response.json() == {
        "subscription": _billing_subscription(status),
        "subscribed": subscribed,
        "may_subscribe": False,
        "trial_days": None,
    }


async def test_billing_me_reports_an_incomplete_subscription_and_offers_a_new_one(
    client, db, fake_billing, user, monkeypatch
):
    monkeypatch.setattr(settings, "BILLING_TRIAL_PERIOD_DAYS", 14)
    await _hold(db, user, _subscription("sub_1", "incomplete"))

    response = await client.get(BILLING_ME)

    assert response.status_code == 200
    assert response.json() == {
        "subscription": _billing_subscription("incomplete"),
        "subscribed": False,
        "may_subscribe": True,
        "trial_days": None,
    }


async def test_billing_me_never_reports_an_ended_subscription(
    client, db, fake_billing, user, monkeypatch
):
    monkeypatch.setattr(settings, "BILLING_TRIAL_PERIOD_DAYS", 14)
    await _hold(
        db, user, _subscription("sub_1", "canceled"), _subscription("sub_2", "incomplete_expired")
    )

    response = await client.get(BILLING_ME)

    assert response.status_code == 200
    assert response.json() == {
        "subscription": None,
        "subscribed": False,
        "may_subscribe": True,
        "trial_days": None,
    }


async def test_billing_me_reads_only_pumpkits_copy_never_stripe(client, db, fake_billing, user):
    """A Subscription only Stripe knows about isn't reported until a sync copies it."""
    await _with_customer(db, user)
    fake_billing.set_subscription(CUSTOMER, _subscription("sub_1", "active"))
    fake_billing.fail_on = {"list_subscriptions"}

    response = await client.get(BILLING_ME)

    assert response.status_code == 200
    assert response.json()["subscription"] is None
    assert response.json()["subscribed"] is False


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
        "/api/v1/billing/me",
        "/api/v1/billing/plans",
        "/api/v1/billing/checkout",
        "/api/v1/billing/portal",
        "/api/v1/stripe/webhook",
    }
