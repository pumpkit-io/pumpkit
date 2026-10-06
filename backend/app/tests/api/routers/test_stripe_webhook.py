"""
Webhooks are nudges (ADR 0004): an event only names the customer that changed,
and Pumpkit syncs its copy from what the billing provider holds now. Tests set
that state on the fake gateway, then send a signed event.
"""

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import func, select

from app.core.billing_gateway import SubscriptionState
from app.db.models import StripeEvent, Subscription

WEBHOOK = "/api/v1/stripe/webhook"

ACTIVE = SubscriptionState(
    id="sub_123",
    status="active",
    price_id="price_123",
    plan_key="pumpkit_pro_monthly",
    current_period_end=datetime(2030, 3, 17, tzinfo=timezone.utc),
    cancel_at_period_end=False,
    created_at=datetime(2030, 2, 17, tzinfo=timezone.utc),
)


async def _count(db, model) -> int:
    # End the previous read so SQLite (WAL) sees the request session's commits.
    await db.commit()
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def _subscription(db) -> Subscription:
    await db.commit()
    return (await db.execute(select(Subscription))).scalar_one()


async def _send(
    client, fake_billing, event_id: str, event_type: str, customer: Optional[str], **extra: Any
):
    """Send a signed event about `customer`; `extra` fields go in its object and are ignored."""
    payload, signature = fake_billing.signed_event(
        event_id=event_id, event_type=event_type, data_object={"customer": customer, **extra}
    )
    return await client.post(WEBHOOK, content=payload, headers={"stripe-signature": signature})


@pytest.fixture
async def stripe_customer(db, user) -> str:
    user.stripe_customer_id = "cus_1"
    await db.commit()
    return "cus_1"


@pytest.mark.parametrize(
    "event_type",
    [
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
        "checkout.session.completed",
    ],
)
async def test_a_nudge_syncs_the_subscription_the_provider_holds(
    client, db, fake_billing, stripe_customer, user, event_type
):
    fake_billing.set_subscription(stripe_customer, replace(ACTIVE, status="past_due"))

    response = await _send(client, fake_billing, "evt_1", event_type, stripe_customer)

    assert response.status_code == 200
    assert response.json() == {"received": True}
    sub = await _subscription(db)
    assert sub.user_id == user.id
    assert sub.stripe_subscription_id == "sub_123"
    assert sub.stripe_customer_id == "cus_1"
    assert (sub.stripe_price_id, sub.plan_key) == ("price_123", "pumpkit_pro_monthly")
    assert sub.status == "past_due"
    assert await _count(db, StripeEvent) == 1


async def test_a_late_active_nudge_after_a_cancellation_leaves_the_subscription_ended(
    client, db, fake_billing, stripe_customer
):
    fake_billing.set_subscription(stripe_customer, replace(ACTIVE, status="canceled"))
    deleted = await _send(
        client, fake_billing, "evt_2", "customer.subscription.deleted", stripe_customer
    )

    # The `updated` event sent before the cancellation arrives last; its payload is ignored.
    late = await _send(
        client,
        fake_billing,
        "evt_1",
        "customer.subscription.updated",
        stripe_customer,
        status="active",
    )

    assert (deleted.status_code, late.status_code) == (200, 200)
    assert (await _subscription(db)).status == "canceled"


async def test_a_nudge_for_an_unknown_customer_is_skipped(client, db, fake_billing, user):
    fake_billing.set_subscription("cus_elsewhere", ACTIVE)

    response = await _send(
        client, fake_billing, "evt_1", "customer.subscription.created", "cus_elsewhere"
    )

    # Recorded, so Stripe doesn't retry a customer Pumpkit will never know.
    assert response.status_code == 200
    assert await _count(db, StripeEvent) == 1
    assert await _count(db, Subscription) == 0


async def test_replaying_an_event_id_is_a_no_op(client, db, fake_billing, stripe_customer):
    fake_billing.set_subscription(stripe_customer, ACTIVE)
    first = await _send(
        client, fake_billing, "evt_1", "customer.subscription.created", stripe_customer
    )

    fake_billing.set_subscription(stripe_customer, replace(ACTIVE, status="past_due"))
    replay = await _send(
        client, fake_billing, "evt_1", "customer.subscription.created", stripe_customer
    )

    assert (first.status_code, replay.status_code) == (200, 200)
    assert (await _subscription(db)).status == "active"
    assert await _count(db, StripeEvent) == 1


async def test_a_provider_failure_during_sync_rolls_back_the_whole_event(
    client, db, fake_billing, stripe_customer, assert_reported_502
):
    fake_billing.set_subscription(stripe_customer, ACTIVE)
    fake_billing.fail_on = {"list_subscriptions"}

    response = await _send(
        client, fake_billing, "evt_fail", "customer.subscription.created", stripe_customer
    )

    # A provider failure is a 502 like everywhere else; Stripe retries any non-2xx.
    assert_reported_502(response)
    # The dedup row rolled back too, so Stripe's retry is processed.
    assert await _count(db, StripeEvent) == 0
    assert await _count(db, Subscription) == 0


@pytest.mark.parametrize(
    "headers",
    [
        {"stripe-signature": "t=1,v1=not-the-signature"},
        {"stripe-signature": "garbage"},
        {},
    ],
    ids=["wrong-signature", "malformed-header", "missing-header"],
)
async def test_an_unverified_event_is_rejected_and_writes_nothing(
    client, db, fake_billing, stripe_customer, headers
):
    fake_billing.set_subscription(stripe_customer, ACTIVE)
    payload, _ = fake_billing.signed_event(
        event_id="evt_1",
        event_type="customer.subscription.created",
        data_object={"customer": stripe_customer},
    )

    response = await client.post(WEBHOOK, content=payload, headers=headers)

    assert response.status_code == 400
    assert await _count(db, StripeEvent) == 0
    assert await _count(db, Subscription) == 0


async def test_a_tampered_payload_is_rejected(client, db, fake_billing, stripe_customer):
    fake_billing.set_subscription(stripe_customer, ACTIVE)
    payload, signature = fake_billing.signed_event(
        event_id="evt_1",
        event_type="customer.subscription.created",
        data_object={"customer": "cus_other"},
    )
    tampered = payload.replace(b"cus_other", stripe_customer.encode())

    response = await client.post(WEBHOOK, content=tampered, headers={"stripe-signature": signature})

    assert response.status_code == 400
    assert await _count(db, Subscription) == 0


async def test_an_unhandled_event_type_is_recorded_and_ignored(
    client, db, fake_billing, stripe_customer
):
    fake_billing.set_subscription(stripe_customer, ACTIVE)

    response = await _send(client, fake_billing, "evt_x", "invoice.created", stripe_customer)

    assert response.status_code == 200
    assert await _count(db, StripeEvent) == 1
    assert await _count(db, Subscription) == 0
