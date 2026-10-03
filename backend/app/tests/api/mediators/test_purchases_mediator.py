from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import stripe
from fastapi import HTTPException

import app.api.hooks.purchases as hooks
import app.api.mediators.purchases as purchases_mediator
import app.api.mediators.stripe as stripe_mediator
import app.api.services.purchases as purchases_service
from app.core.purchases import PRODUCTS
from app.db.models import Purchase

from .stripe_helpers import patch_construct_event, webhook_payload

PRODUCT = PRODUCTS[0]


@pytest.fixture
def hook_spies(monkeypatch):
    spies = SimpleNamespace(paid=AsyncMock(), reversed=AsyncMock(), reinstated=AsyncMock())
    monkeypatch.setattr(hooks, "on_purchase_paid", spies.paid)
    monkeypatch.setattr(hooks, "on_purchase_reversed", spies.reversed)
    monkeypatch.setattr(hooks, "on_purchase_reinstated", spies.reinstated)
    return spies


@pytest.fixture
def stripe_stubs(monkeypatch):
    created = {}

    def _create_session(**params):
        created.update(params)
        return SimpleNamespace(id="cs_test_1", url="https://checkout.stripe.test/cs_test_1")

    monkeypatch.setattr(purchases_mediator.stripe.checkout.Session, "create", _create_session)
    monkeypatch.setattr(
        purchases_mediator.stripe_customers_service,
        "ensure_stripe_customer",
        AsyncMock(return_value="cus_1"),
    )
    monkeypatch.setattr(purchases_mediator, "_resolve_charge_id", AsyncMock(return_value="ch_1"))
    patch_construct_event(monkeypatch)
    return created


async def _checkout(db, user) -> str:
    response = await purchases_mediator.create_checkout_session(
        db, user=user, product_id=PRODUCT.id
    )
    assert response.session_id == "cs_test_1"
    purchase = await purchases_service.get_purchase_by_session_id(db, session_id="cs_test_1")
    assert purchase is not None
    return purchase.id


async def _get_purchase(db, purchase_id: str) -> Purchase:
    purchase = await purchases_service.get_purchase_by_id(db, purchase_id=purchase_id)
    assert purchase is not None
    return purchase


def _completed(
    purchase_id: str,
    user_id: str,
    *,
    subtotal: int = PRODUCT.amount_cents,
    currency: str = PRODUCT.currency,
) -> dict:
    return {
        "id": "cs_test_1",
        "object": "checkout.session",
        "payment_status": "paid",
        "amount_subtotal": subtotal,
        "amount_total": subtotal,
        "total_details": {"amount_tax": 0},
        "currency": currency,
        "payment_intent": "pi_1",
        "client_reference_id": user_id,
        "metadata": {
            "kind": "purchase",
            "purchase_id": purchase_id,
            "product_id": PRODUCT.id,
            "user_id": user_id,
        },
    }


async def _send(db, event_id: str, event_type: str, obj: dict) -> None:
    await stripe_mediator.handle_webhook(
        db=db, payload=webhook_payload(event_id, event_type, obj), signature="sig"
    )


async def test_checkout_creates_pending_row_with_catalog_price(db, user, stripe_stubs):
    purchase_id = await _checkout(db, user)
    purchase = await _get_purchase(db, purchase_id)
    assert purchase.status == "pending"
    line = stripe_stubs["line_items"][0]["price_data"]
    assert stripe_stubs["mode"] == "payment"
    assert line["unit_amount"] == PRODUCT.amount_cents
    assert line["currency"] == PRODUCT.currency
    assert stripe_stubs["metadata"]["purchase_id"] == purchase_id
    assert stripe_stubs["payment_intent_data"]["metadata"]["purchase_id"] == purchase_id


async def test_checkout_rejects_unknown_product(db, user, stripe_stubs):
    with pytest.raises(HTTPException) as exc:
        await purchases_mediator.create_checkout_session(db, user=user, product_id="nope")
    assert exc.value.status_code == 400


async def test_completed_marks_paid_and_calls_hook_once(db, user, stripe_stubs, hook_spies):
    purchase_id = await _checkout(db, user)
    await _send(db, "evt_c1", "checkout.session.completed", _completed(purchase_id, user.id))
    await _send(
        db, "evt_c1", "checkout.session.completed", _completed(purchase_id, user.id)
    )  # replay
    purchase = await _get_purchase(db, purchase_id)
    assert purchase.status == "paid"
    assert purchase.stripe_charge_id == "ch_1"
    assert hook_spies.paid.await_count == 1


async def test_amount_mismatch_marks_failed_without_hook(db, user, stripe_stubs, hook_spies):
    purchase_id = await _checkout(db, user)
    await _send(
        db, "evt_bad", "checkout.session.completed", _completed(purchase_id, user.id, subtotal=1)
    )
    purchase = await _get_purchase(db, purchase_id)
    assert purchase.status == "failed"
    hook_spies.paid.assert_not_awaited()


async def test_currency_mismatch_marks_failed_without_hook(db, user, stripe_stubs, hook_spies):
    purchase_id = await _checkout(db, user)
    await _send(
        db,
        "evt_cur",
        "checkout.session.completed",
        _completed(purchase_id, user.id, currency="usd"),
    )
    purchase = await _get_purchase(db, purchase_id)
    assert purchase.status == "failed"
    hook_spies.paid.assert_not_awaited()


async def test_unpaid_completed_session_stays_pending(db, user, stripe_stubs, hook_spies):
    purchase_id = await _checkout(db, user)
    obj = _completed(purchase_id, user.id)
    obj["payment_status"] = "unpaid"
    await _send(db, "evt_unpaid", "checkout.session.completed", obj)
    purchase = await _get_purchase(db, purchase_id)
    assert purchase.status == "pending"
    hook_spies.paid.assert_not_awaited()


async def test_partial_then_full_refund(db, user, stripe_stubs, hook_spies):
    purchase_id = await _checkout(db, user)
    await _send(db, "evt_c", "checkout.session.completed", _completed(purchase_id, user.id))
    charge = {
        "id": "ch_1",
        "payment_intent": "pi_1",
        "amount": PRODUCT.amount_cents,
        "amount_refunded": 100,
    }
    await _send(db, "evt_r1", "charge.refunded", charge)
    await _send(db, "evt_r1", "charge.refunded", charge)  # replay
    purchase = await _get_purchase(db, purchase_id)
    assert purchase.status == "partially_refunded"
    assert purchase.refunded_amount_cents == 100

    await _send(
        db, "evt_r2", "charge.refunded", {**charge, "amount_refunded": PRODUCT.amount_cents}
    )
    await db.refresh(purchase)
    assert purchase.status == "refunded"
    reasons = [call.args[2] for call in hook_spies.reversed.await_args_list]
    assert reasons == ["partially_refunded", "refunded"]


async def test_dispute_withdrawn_then_reinstated(db, user, stripe_stubs, hook_spies):
    purchase_id = await _checkout(db, user)
    await _send(db, "evt_c", "checkout.session.completed", _completed(purchase_id, user.id))
    dispute = {"id": "dp_1", "charge": "ch_1", "payment_intent": "pi_1"}
    await _send(db, "evt_d1", "charge.dispute.funds_withdrawn", dispute)
    purchase = await _get_purchase(db, purchase_id)
    assert purchase.status == "disputed"
    assert hook_spies.reversed.await_args.args[2] == "disputed"

    await _send(db, "evt_d2", "charge.dispute.funds_reinstated", dispute)
    await db.refresh(purchase)
    assert purchase.status == "paid"
    hook_spies.reinstated.assert_awaited_once()


async def test_payment_failed_then_paid_ends_paid(db, user, stripe_stubs, hook_spies):
    purchase_id = await _checkout(db, user)
    pi = {"id": "pi_1", "metadata": {"kind": "purchase", "purchase_id": purchase_id}}
    await _send(db, "evt_f", "payment_intent.payment_failed", pi)
    await _send(db, "evt_c", "checkout.session.completed", _completed(purchase_id, user.id))
    purchase = await _get_purchase(db, purchase_id)
    assert purchase.status == "paid"
    hook_spies.paid.assert_awaited_once()


async def test_session_expired_fails_pending_without_hooks(db, user, stripe_stubs, hook_spies):
    purchase_id = await _checkout(db, user)
    await _send(db, "evt_e", "checkout.session.expired", _completed(purchase_id, user.id))
    purchase = await _get_purchase(db, purchase_id)
    assert purchase.status == "failed"
    hook_spies.paid.assert_not_awaited()
    hook_spies.reversed.assert_not_awaited()
    hook_spies.reinstated.assert_not_awaited()


async def test_session_expired_after_paid_stays_paid(db, user, stripe_stubs, hook_spies):
    purchase_id = await _checkout(db, user)
    await _send(db, "evt_c", "checkout.session.completed", _completed(purchase_id, user.id))
    await _send(db, "evt_e", "checkout.session.expired", _completed(purchase_id, user.id))
    purchase = await _get_purchase(db, purchase_id)
    assert purchase.status == "paid"


async def test_async_payment_failed_fails_pending(db, user, stripe_stubs, hook_spies):
    purchase_id = await _checkout(db, user)
    await _send(
        db, "evt_a", "checkout.session.async_payment_failed", _completed(purchase_id, user.id)
    )
    purchase = await _get_purchase(db, purchase_id)
    assert purchase.status == "failed"


async def test_async_payment_succeeded_marks_paid(db, user, stripe_stubs, hook_spies):
    purchase_id = await _checkout(db, user)
    unpaid = {**_completed(purchase_id, user.id), "payment_status": "unpaid"}
    await _send(db, "evt_c", "checkout.session.completed", unpaid)
    await _send(
        db, "evt_s", "checkout.session.async_payment_succeeded", _completed(purchase_id, user.id)
    )
    purchase = await _get_purchase(db, purchase_id)
    assert purchase.status == "paid"
    hook_spies.paid.assert_awaited_once()


async def test_completed_without_row_creates_from_metadata(db, user, stripe_stubs, hook_spies):
    obj = _completed("purchase_missing", user.id)
    obj["id"] = "cs_orphan"
    await _send(db, "evt_o", "checkout.session.completed", obj)
    purchase = await purchases_service.get_purchase_by_session_id(db, session_id="cs_orphan")
    assert purchase is not None
    assert purchase.id == "purchase_missing"
    assert purchase.status == "paid"
    hook_spies.paid.assert_awaited_once()


async def test_metadata_purchase_id_must_match_session(db, user, stripe_stubs, hook_spies):
    purchase_id = await _checkout(db, user)
    obj = _completed(purchase_id, user.id)
    obj["id"] = "cs_other"
    await _send(db, "evt_m", "checkout.session.completed", obj)
    purchase = await _get_purchase(db, purchase_id)
    assert purchase.status == "pending"
    hook_spies.paid.assert_not_awaited()


async def test_resolve_charge_id_from_expanded_stripe_object(monkeypatch):
    pi = stripe.PaymentIntent.construct_from(
        {
            "id": "pi_1",
            "object": "payment_intent",
            "latest_charge": {"id": "ch_real", "object": "charge"},
        },
        "sk_test",
    )
    monkeypatch.setattr(stripe.PaymentIntent, "retrieve", lambda *a, **k: pi)
    assert await purchases_mediator._resolve_charge_id("pi_1") == "ch_real"


async def test_resolve_charge_id_from_string(monkeypatch):
    pi = stripe.PaymentIntent.construct_from(
        {"id": "pi_1", "object": "payment_intent", "latest_charge": "ch_str"}, "sk_test"
    )
    monkeypatch.setattr(stripe.PaymentIntent, "retrieve", lambda *a, **k: pi)
    assert await purchases_mediator._resolve_charge_id("pi_1") == "ch_str"


async def test_refund_for_unknown_charge_is_ignored(db, stripe_stubs, hook_spies):
    await _send(
        db,
        "evt_u",
        "charge.refunded",
        {"id": "ch_other", "payment_intent": "pi_other", "amount": 500, "amount_refunded": 500},
    )
    hook_spies.reversed.assert_not_awaited()


async def test_hook_exception_rolls_back_purchase_and_event(db, user, stripe_stubs, hook_spies):
    user_id = user.id  # rollback expires ORM attributes; read before it
    purchase_id = await _checkout(db, user)
    hook_spies.paid.side_effect = RuntimeError("grant failed")
    with pytest.raises(RuntimeError):
        await _send(db, "evt_boom", "checkout.session.completed", _completed(purchase_id, user_id))
    purchase = await _get_purchase(db, purchase_id)
    assert purchase.status == "pending"
    # Retry after the bug is fixed succeeds because the event row was rolled back.
    hook_spies.paid.side_effect = None
    await _send(db, "evt_boom", "checkout.session.completed", _completed(purchase_id, user_id))
    await db.refresh(purchase)
    assert purchase.status == "paid"
