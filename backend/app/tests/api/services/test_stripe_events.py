from __future__ import annotations

import app.api.services.stripe_events as stripe_events_service


async def test_first_record_returns_true(db):
    inserted = await stripe_events_service.try_record_event(
        db, event_id="evt_1", event_type="checkout.session.completed"
    )
    await db.commit()
    assert inserted is True


async def test_duplicate_record_returns_false(db):
    await stripe_events_service.try_record_event(
        db, event_id="evt_dup", event_type="charge.refunded"
    )
    await db.commit()

    second = await stripe_events_service.try_record_event(
        db, event_id="evt_dup", event_type="charge.refunded"
    )
    assert second is False


async def test_namespace_isolates_event_ids(db):
    """Two namespaces consuming the same Stripe event both record."""
    a = await stripe_events_service.try_record_event(
        db,
        event_id="evt_shared",
        event_type="charge.refunded",
        namespace="purchases",
    )
    await db.commit()
    b = await stripe_events_service.try_record_event(
        db,
        event_id="evt_shared",
        event_type="charge.refunded",
        namespace="subscription",
    )
    await db.commit()
    assert a is True
    assert b is True

    # And duplicate within the same namespace still returns False.
    c = await stripe_events_service.try_record_event(
        db,
        event_id="evt_shared",
        event_type="charge.refunded",
        namespace="purchases",
    )
    assert c is False
