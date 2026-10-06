from dataclasses import replace
from datetime import datetime, timezone

import pytest

import app.api.services.subscriptions as subscriptions_service
from app.core.billing_gateway import BillingProviderError, FakeBillingGateway, SubscriptionState

CUSTOMER = "cus_1"

RUNNING = SubscriptionState(
    id="sub_new",
    status="active",
    price_id="price_monthly",
    plan_key="pumpkit_pro_monthly",
    current_period_end=datetime(2026, 11, 6, tzinfo=timezone.utc),
    cancel_at_period_end=False,
)
ENDED = SubscriptionState(
    id="sub_old",
    status="canceled",
    price_id="price_legacy",
    plan_key=None,
    current_period_end=datetime(2026, 9, 1, tzinfo=timezone.utc),
    cancel_at_period_end=False,
)


async def test_sync_copies_every_subscription_of_the_customer(db, user):
    gateway = FakeBillingGateway()
    gateway.set_subscription(CUSTOMER, RUNNING)
    gateway.set_subscription(CUSTOMER, ENDED)

    await subscriptions_service.sync_customer(db, gateway, user_id=user.id, customer_id=CUSTOMER)

    running = await subscriptions_service.get_subscription_by_stripe_id(db, "sub_new")
    assert running is not None
    assert (running.user_id, running.stripe_customer_id) == (user.id, CUSTOMER)
    assert (running.status, running.stripe_price_id, running.plan_key) == (
        "active",
        "price_monthly",
        "pumpkit_pro_monthly",
    )
    assert running.current_period_end is not None
    assert running.current_period_end.replace(tzinfo=timezone.utc) == RUNNING.current_period_end
    assert running.cancel_at_period_end is False
    ended = await subscriptions_service.get_subscription_by_stripe_id(db, "sub_old")
    assert ended is not None
    assert (ended.status, ended.plan_key) == ("canceled", None)


async def test_sync_updates_a_subscription_to_what_the_provider_holds_now(db, user):
    gateway = FakeBillingGateway()
    gateway.set_subscription(CUSTOMER, RUNNING)
    await subscriptions_service.sync_customer(db, gateway, user_id=user.id, customer_id=CUSTOMER)

    gateway.set_subscription(CUSTOMER, replace(RUNNING, status="past_due"))
    await subscriptions_service.sync_customer(db, gateway, user_id=user.id, customer_id=CUSTOMER)

    synced = await subscriptions_service.get_subscription_by_stripe_id(db, "sub_new")
    assert synced is not None
    assert synced.status == "past_due"


@pytest.mark.parametrize("ended_status", ["canceled", "incomplete_expired"])
async def test_sync_never_overwrites_an_ended_subscription(db, user, ended_status):
    gateway = FakeBillingGateway()
    gateway.set_subscription(CUSTOMER, replace(RUNNING, status=ended_status))
    await subscriptions_service.sync_customer(db, gateway, user_id=user.id, customer_id=CUSTOMER)

    # A provider answer that would bring it back (a bug, not a real Stripe state).
    gateway.set_subscription(CUSTOMER, replace(RUNNING, status="active"))
    await subscriptions_service.sync_customer(db, gateway, user_id=user.id, customer_id=CUSTOMER)

    synced = await subscriptions_service.get_subscription_by_stripe_id(db, "sub_new")
    assert synced is not None
    assert synced.status == ended_status


async def test_sync_raises_when_the_provider_fails(db, user):
    gateway = FakeBillingGateway(fail_on={"list_subscriptions"})

    with pytest.raises(BillingProviderError):
        await subscriptions_service.sync_customer(
            db, gateway, user_id=user.id, customer_id=CUSTOMER
        )
