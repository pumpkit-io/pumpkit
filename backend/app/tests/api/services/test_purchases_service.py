import app.api.services.purchases as purchases_service
from app.core.purchases import PRODUCTS

PRODUCT = PRODUCTS[0]


async def _pending(db, user, *, purchase_id="purchase_1", session_id="cs_1"):
    purchase = await purchases_service.create_pending_purchase(
        db,
        purchase_id=purchase_id,
        user_id=user.id,
        product=PRODUCT,
        stripe_checkout_session_id=session_id,
    )
    await db.commit()
    return purchase


async def test_create_and_lookup(db, user):
    purchase = await _pending(db, user)
    assert purchase.status == "pending"
    assert purchase.amount_subtotal_cents == PRODUCT.amount_cents
    assert purchase.currency == PRODUCT.currency
    by_session = await purchases_service.get_purchase_by_session_id(db, session_id="cs_1")
    assert by_session is not None and by_session.id == "purchase_1"
    assert (await purchases_service.get_purchase_by_id(db, purchase_id="purchase_1")) is not None


async def test_paid_then_lookup_by_stripe_ids(db, user):
    purchase = await _pending(db, user)
    await purchases_service.mark_purchase_paid(
        db,
        purchase,
        payment_intent_id="pi_1",
        charge_id="ch_1",
        amount_subtotal_cents=PRODUCT.amount_cents,
        amount_tax_cents=0,
        amount_total_cents=PRODUCT.amount_cents,
    )
    await db.commit()
    assert purchase.status == "paid"
    by_intent = await purchases_service.get_purchase_by_payment_intent_id(
        db, payment_intent_id="pi_1"
    )
    assert by_intent is not None and by_intent.id == purchase.id
    by_charge = await purchases_service.get_purchase_by_charge_id(db, charge_id="ch_1")
    assert by_charge is not None and by_charge.id == purchase.id


async def test_dispute_reinstated_restores_partial_refund_status(db, user):
    purchase = await _pending(db, user)
    await purchases_service.mark_purchase_refunded(
        db, purchase, refunded_amount_cents=100, is_full=False, charge_id="ch_9"
    )
    assert purchase.status == "partially_refunded"
    assert purchase.stripe_charge_id == "ch_9"
    await purchases_service.mark_purchase_disputed(db, purchase, charge_id=None)
    assert purchase.status == "disputed"
    await purchases_service.mark_purchase_dispute_reinstated(db, purchase)
    assert purchase.status == "partially_refunded"


async def test_list_purchases_newest_first(db, user):
    await _pending(db, user, purchase_id="purchase_a", session_id="cs_a")
    await _pending(db, user, purchase_id="purchase_b", session_id="cs_b")
    rows = await purchases_service.list_purchases_for_user(db, user_id=user.id)
    assert {r.id for r in rows} == {"purchase_a", "purchase_b"}
    assert rows[0].created_at >= rows[1].created_at
