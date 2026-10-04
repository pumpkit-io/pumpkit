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
        db, event_id="evt_dup", event_type="customer.subscription.updated"
    )
    await db.commit()

    second = await stripe_events_service.try_record_event(
        db, event_id="evt_dup", event_type="customer.subscription.updated"
    )
    assert second is False
