from dataclasses import replace
from datetime import datetime, timezone

import pytest

import app.api.services.subscriptions as subscriptions_service
from app.core.billing_gateway import BillingProviderError, FakeBillingGateway, SubscriptionState
from app.core.config import settings
from app.db.models import User

CUSTOMER = "cus_1"

RUNNING = SubscriptionState(
    id="sub_new",
    status="active",
    price_id="price_monthly",
    plan_key="pumpkit_pro_monthly",
    current_period_end=datetime(2026, 11, 6, tzinfo=timezone.utc),
    cancel_at_period_end=False,
    created_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
)
ENDED = SubscriptionState(
    id="sub_old",
    status="canceled",
    price_id="price_legacy",
    plan_key=None,
    current_period_end=datetime(2026, 9, 1, tzinfo=timezone.utc),
    cancel_at_period_end=False,
    created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
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


async def _hold(db, user, *states: SubscriptionState) -> None:
    """Make the User's copy hold `states`, the way a sync would."""
    gateway = FakeBillingGateway()
    for state in states:
        gateway.set_subscription(CUSTOMER, state)
    await subscriptions_service.sync_customer(db, gateway, user_id=user.id, customer_id=CUSTOMER)


async def test_a_user_who_never_had_a_subscription_may_subscribe_with_the_trial(
    db, user, monkeypatch
):
    monkeypatch.setattr(settings, "BILLING_TRIAL_PERIOD_DAYS", 14)

    offer = await subscriptions_service.get_subscription_offer(db, user_id=user.id)

    assert offer == subscriptions_service.SubscriptionOffer(may_subscribe=True, trial_days=14)


async def test_a_user_who_never_had_a_subscription_gets_no_trial_when_trials_are_off(
    db, user, monkeypatch
):
    monkeypatch.setattr(settings, "BILLING_TRIAL_PERIOD_DAYS", 0)

    offer = await subscriptions_service.get_subscription_offer(db, user_id=user.id)

    assert offer == subscriptions_service.SubscriptionOffer(may_subscribe=True, trial_days=None)


@pytest.mark.parametrize("running_status", ["trialing", "active", "past_due", "unpaid", "paused"])
async def test_a_user_with_a_running_subscription_may_not_subscribe(db, user, running_status):
    await _hold(db, user, ENDED, replace(RUNNING, status=running_status))

    offer = await subscriptions_service.get_subscription_offer(db, user_id=user.id)

    assert offer == subscriptions_service.SubscriptionOffer(may_subscribe=False, trial_days=None)


@pytest.mark.parametrize("status", ["canceled", "incomplete_expired", "incomplete"])
async def test_a_user_with_no_running_subscription_may_subscribe_without_a_trial(
    db, user, status, monkeypatch
):
    """Ended and `incomplete` Subscriptions don't block, but they use up the Trial."""
    monkeypatch.setattr(settings, "BILLING_TRIAL_PERIOD_DAYS", 14)
    await _hold(db, user, replace(RUNNING, status=status))

    offer = await subscriptions_service.get_subscription_offer(db, user_id=user.id)

    assert offer == subscriptions_service.SubscriptionOffer(may_subscribe=True, trial_days=None)


async def test_the_users_incomplete_subscriptions_are_listed(db, user):
    await _hold(
        db,
        user,
        ENDED,
        replace(RUNNING, id="sub_a", status="incomplete"),
        replace(RUNNING, id="sub_b", status="incomplete"),
        replace(RUNNING, id="sub_c", status="incomplete_expired"),
    )

    incomplete = await subscriptions_service.list_incomplete_subscriptions(db, user_id=user.id)

    assert sorted(s.stripe_subscription_id for s in incomplete) == ["sub_a", "sub_b"]


async def test_another_users_subscriptions_are_not_counted_as_theirs(db, user):
    other = User(email="bob@example.com", display_name="Bob")
    db.add(other)
    await db.flush()
    gateway = FakeBillingGateway()
    gateway.set_subscription("cus_bob", replace(RUNNING, id="sub_bob", status="incomplete"))
    await subscriptions_service.sync_customer(db, gateway, user_id=other.id, customer_id="cus_bob")

    assert await subscriptions_service.list_incomplete_subscriptions(db, user_id=user.id) == []
    offer = await subscriptions_service.get_subscription_offer(db, user_id=user.id)
    assert offer.may_subscribe is True


async def test_a_user_with_no_subscription_has_none_and_is_not_subscribed(db, user):
    subscription = await subscriptions_service.get_user_subscription(db, user_id=user.id)

    assert subscription is None
    assert subscriptions_service.is_subscribed(subscription) is False


@pytest.mark.parametrize(
    ("status", "subscribed"),
    [
        ("trialing", True),
        ("active", True),
        ("past_due", True),
        ("unpaid", False),
        ("paused", False),
        ("incomplete", False),
    ],
)
async def test_the_user_is_subscribed_only_while_trialing_active_or_past_due(
    db, user, status, subscribed
):
    await _hold(db, user, replace(RUNNING, status=status))

    subscription = await subscriptions_service.get_user_subscription(db, user_id=user.id)

    assert subscription is not None
    assert subscription.status == status
    assert subscriptions_service.is_subscribed(subscription) is subscribed


async def test_the_users_running_subscription_beats_an_incomplete_one(db, user):
    await _hold(
        db,
        user,
        replace(RUNNING, id="sub_running", status="past_due"),
        replace(RUNNING, id="sub_incomplete", status="incomplete"),
    )

    subscription = await subscriptions_service.get_user_subscription(db, user_id=user.id)

    assert subscription is not None
    assert subscription.stripe_subscription_id == "sub_running"


async def test_an_ended_subscription_is_never_the_users_subscription(db, user):
    await _hold(
        db,
        user,
        ENDED,
        replace(RUNNING, id="sub_expired", status="incomplete_expired"),
    )

    subscription = await subscriptions_service.get_user_subscription(db, user_id=user.id)

    assert subscription is None
    assert subscriptions_service.is_subscribed(subscription) is False


@pytest.mark.parametrize("synced_first", ["sub_older", "sub_newer"])
async def test_the_users_newest_incomplete_subscription_is_the_one_stripe_created_last(
    db, user, synced_first
):
    """Rows synced in one transaction share a write time: only Stripe's says which is newer."""
    older = replace(
        RUNNING,
        id="sub_older",
        status="incomplete",
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    newer = replace(
        RUNNING,
        id="sub_newer",
        status="incomplete",
        created_at=datetime(2026, 10, 2, tzinfo=timezone.utc),
    )
    await _hold(db, user, *((older, newer) if synced_first == "sub_older" else (newer, older)))

    subscription = await subscriptions_service.get_user_subscription(db, user_id=user.id)

    assert subscription is not None
    assert subscription.stripe_subscription_id == "sub_newer"


async def test_incomplete_subscriptions_stripe_created_at_once_are_told_apart_by_id(db, user):
    await _hold(
        db,
        user,
        replace(RUNNING, id="sub_b", status="incomplete"),
        replace(RUNNING, id="sub_a", status="incomplete"),
    )

    subscription = await subscriptions_service.get_user_subscription(db, user_id=user.id)

    assert subscription is not None
    assert subscription.stripe_subscription_id == "sub_b"
