from datetime import timezone

from sqlalchemy import func, select

import app.api.mediators.stripe as stripe_mediator
from app.db.models import StripeEvent, Subscription

from .stripe_helpers import patch_construct_event, webhook_payload


def _subscription_object(customer_id: str, status: str = "active") -> dict:
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
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def test_subscription_event_upserts_row(db, user, monkeypatch):
    patch_construct_event(monkeypatch)
    user.stripe_customer_id = "cus_1"
    await db.commit()

    payload = webhook_payload("evt_1", "customer.subscription.created", _subscription_object("cus_1"))
    await stripe_mediator.handle_webhook(db=db, payload=payload, signature="sig")

    sub = (await db.execute(select(Subscription))).scalar_one()
    assert sub.status == "active"
    assert sub.stripe_price_id == "price_123"
    assert await _count(db, StripeEvent) == 1


async def test_replayed_event_is_ignored(db, user, monkeypatch):
    patch_construct_event(monkeypatch)
    user.stripe_customer_id = "cus_1"
    await db.commit()

    await stripe_mediator.handle_webhook(
        db=db,
        payload=webhook_payload("evt_1", "customer.subscription.created", _subscription_object("cus_1")),
        signature="sig",
    )
    # Same event id, different content: must be ignored entirely.
    await stripe_mediator.handle_webhook(
        db=db,
        payload=webhook_payload("evt_1", "customer.subscription.updated", _subscription_object("cus_1", "canceled")),
        signature="sig",
    )
    sub = (await db.execute(select(Subscription))).scalar_one()
    assert sub.status == "active"


async def test_handler_exception_rolls_back_event_row(db, user, monkeypatch):
    patch_construct_event(monkeypatch)

    async def _explode(db, *, event_type, event_id, data_object):
        raise RuntimeError("handler failed")

    monkeypatch.setattr(stripe_mediator, "_dispatch_event", _explode)
    payload = webhook_payload("evt_fail", "customer.subscription.created", _subscription_object("cus_1"))

    try:
        await stripe_mediator.handle_webhook(db=db, payload=payload, signature="sig")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")

    assert await _count(db, StripeEvent) == 0


async def test_unknown_event_type_is_recorded_and_ignored(db, monkeypatch):
    patch_construct_event(monkeypatch)
    await stripe_mediator.handle_webhook(
        db=db, payload=webhook_payload("evt_x", "invoice.created", {"id": "in_1"}), signature="sig"
    )
    assert await _count(db, StripeEvent) == 1


async def test_handlers_receive_plain_dicts(db, monkeypatch):
    patch_construct_event(monkeypatch)
    seen = {}

    async def _capture(db, *, event_type, event_id, data_object):
        seen["type"] = type(data_object)

    monkeypatch.setattr(stripe_mediator, "_dispatch_event", _capture)
    await stripe_mediator.handle_webhook(
        db=db, payload=webhook_payload("evt_d", "invoice.created", {"id": "in_1"}), signature="sig"
    )
    assert seen["type"] is dict


async def test_subscription_period_end_falls_back_to_item(db, user, monkeypatch):
    patch_construct_event(monkeypatch)
    user.stripe_customer_id = "cus_1"
    await db.commit()

    obj = _subscription_object("cus_1")
    del obj["current_period_end"]
    obj["items"] = {"data": [{"price": {"id": "price_123"}, "current_period_end": 1_900_000_000}]}
    payload = webhook_payload("evt_item", "customer.subscription.updated", obj)
    await stripe_mediator.handle_webhook(db=db, payload=payload, signature="sig")

    sub = (await db.execute(select(Subscription))).scalar_one()
    assert sub.current_period_end is not None
    assert int(sub.current_period_end.replace(tzinfo=timezone.utc).timestamp()) == 1_900_000_000
