from datetime import timezone
from typing import Any

import pytest
from sqlalchemy import func, select

from app.db.models import StripeEvent, Subscription

WEBHOOK = "/api/v1/stripe/webhook"


def _subscription_object(customer_id: str, status: str = "active") -> dict[str, Any]:
    return {
        "id": "sub_123",
        "object": "subscription",
        "customer": customer_id,
        "status": status,
        "cancel_at_period_end": False,
        "current_period_end": 1_900_000_000,
        "items": {"data": [{"price": {"id": "price_123"}}]},
    }


async def _count(db, model) -> int:
    # End the previous read so SQLite (WAL) sees the request session's commits.
    await db.commit()
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def _send(client, fake_billing, event_id: str, event_type: str, data_object: dict):
    payload, signature = fake_billing.signed_event(
        event_id=event_id, event_type=event_type, data_object=data_object
    )
    return await client.post(WEBHOOK, content=payload, headers={"stripe-signature": signature})


@pytest.fixture
async def stripe_customer(db, user) -> str:
    user.stripe_customer_id = "cus_1"
    await db.commit()
    return "cus_1"


@pytest.mark.parametrize(
    ("event_type", "status"),
    [
        ("customer.subscription.created", "trialing"),
        ("customer.subscription.updated", "active"),
        ("customer.subscription.deleted", "canceled"),
    ],
)
async def test_signed_subscription_event_upserts_the_subscription(
    client, db, fake_billing, stripe_customer, user, event_type, status
):
    response = await _send(
        client, fake_billing, "evt_1", event_type, _subscription_object(stripe_customer, status)
    )

    assert response.status_code == 200
    assert response.json() == {"received": True}
    await db.commit()
    sub = (await db.execute(select(Subscription))).scalar_one()
    assert sub.user_id == user.id
    assert sub.stripe_subscription_id == "sub_123"
    assert sub.stripe_customer_id == "cus_1"
    assert sub.stripe_price_id == "price_123"
    assert sub.status == status
    assert await _count(db, StripeEvent) == 1


async def test_replaying_an_event_id_is_a_no_op(client, db, fake_billing, stripe_customer):
    first = await _send(
        client,
        fake_billing,
        "evt_1",
        "customer.subscription.created",
        _subscription_object(stripe_customer, "active"),
    )
    # Same event ID, different content: must be ignored entirely.
    replay = await _send(
        client,
        fake_billing,
        "evt_1",
        "customer.subscription.updated",
        _subscription_object(stripe_customer, "canceled"),
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    await db.commit()
    sub = (await db.execute(select(Subscription))).scalar_one()
    assert sub.status == "active"
    assert await _count(db, StripeEvent) == 1


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
    payload, _ = fake_billing.signed_event(
        event_id="evt_1",
        event_type="customer.subscription.created",
        data_object=_subscription_object(stripe_customer),
    )

    response = await client.post(WEBHOOK, content=payload, headers=headers)

    assert response.status_code == 400
    assert await _count(db, StripeEvent) == 0
    assert await _count(db, Subscription) == 0


async def test_a_tampered_payload_is_rejected(client, db, fake_billing, stripe_customer):
    payload, signature = fake_billing.signed_event(
        event_id="evt_1",
        event_type="customer.subscription.created",
        data_object=_subscription_object(stripe_customer, "incomplete"),
    )
    tampered = payload.replace(b'"incomplete"', b'"active"')

    response = await client.post(WEBHOOK, content=tampered, headers={"stripe-signature": signature})

    assert response.status_code == 400
    assert await _count(db, Subscription) == 0


async def test_a_handler_failure_rolls_back_the_whole_event(
    client, db, fake_billing, stripe_customer, assert_reported_500
):
    # The handler can't apply a Subscription without a status, so it raises mid-transaction.
    broken = _subscription_object(stripe_customer)
    del broken["status"]

    response = await _send(
        client, fake_billing, "evt_fail", "customer.subscription.created", broken
    )

    assert_reported_500(response)
    # The dedup row rolled back too, so Stripe's retry is processed.
    assert await _count(db, StripeEvent) == 0
    assert await _count(db, Subscription) == 0


async def test_an_unhandled_event_type_is_recorded_and_ignored(client, db, fake_billing):
    response = await _send(client, fake_billing, "evt_x", "invoice.created", {"id": "in_1"})

    assert response.status_code == 200
    assert await _count(db, StripeEvent) == 1
    assert await _count(db, Subscription) == 0


async def test_subscription_period_end_falls_back_to_the_first_item(
    client, db, fake_billing, stripe_customer
):
    # Current Stripe API versions put the period end on the subscription items.
    obj = _subscription_object(stripe_customer)
    del obj["current_period_end"]
    obj["items"] = {"data": [{"price": {"id": "price_123"}, "current_period_end": 1_900_000_000}]}

    response = await _send(client, fake_billing, "evt_item", "customer.subscription.updated", obj)

    assert response.status_code == 200
    await db.commit()
    sub = (await db.execute(select(Subscription))).scalar_one()
    assert sub.current_period_end is not None
    assert int(sub.current_period_end.replace(tzinfo=timezone.utc).timestamp()) == 1_900_000_000
