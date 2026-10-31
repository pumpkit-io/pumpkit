"""
Buying a Top-up (ADR 0017): its Checkout, and its sync from Stripe when a webhook nudges about a
paid Checkout, a refund or a dispute (ADR 0004). What a Top-up has left shows in `GET /usage`.
"""

from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from pumpkit.billing import mediator as billing_mediator
from pumpkit.billing.gateway import OneOffPrice, TopUpCheckoutCall, TopUpPurchase
from pumpkit.billing.models import Subscription, TermsAcceptance
from pumpkit.billing.subscription_status import SubscriptionStatus
from pumpkit.billing.terms import TERMS_VERSION
from pumpkit.core.config import settings

TOP_UP_CHECKOUT = "/api/v1/billing/top-ups/checkout"
PLANS = "/api/v1/billing/plans"
USAGE = "/api/v1/usage"
WEBHOOK = "/api/v1/stripe/webhook"
TOP_UP_KEY = "pumpkit_top_up"
ACCEPTANCE = {
    "terms_version": TERMS_VERSION,
    "accepted_terms": True,
    "requested_immediate_start": True,
    "approved_specific_clauses": True,
}
TOP_UP_PRICE = OneOffPrice(key=TOP_UP_KEY, price_id="price_top_up", amount=1000, currency="eur")


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
def sells_top_ups(monkeypatch, fake_billing):
    monkeypatch.setattr(settings, "BILLING_TOP_UP_KEY", TOP_UP_KEY)
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 500)
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 100)
    monkeypatch.setattr(settings, "X_LINK_POSTS_MONTHLY_CAP", 10)
    fake_billing.prices = [TOP_UP_PRICE]


@pytest.fixture
def analytics(monkeypatch) -> MagicMock:
    fake = MagicMock()
    monkeypatch.setattr(billing_mediator, "posthog_client", fake)
    return fake


@pytest.fixture
async def stripe_customer(db, user) -> str:
    user.stripe_customer_id = "cus_1"
    await db.commit()
    return "cus_1"


async def _set_status(db, subscription: Subscription, status: SubscriptionStatus) -> None:
    subscription.status = status
    db.add(subscription)
    await db.commit()


async def _acceptances(db) -> list[TermsAcceptance]:
    await db.commit()
    return list((await db.execute(select(TermsAcceptance))).scalars())


async def _send(client, fake_billing, event_id: str, event_type: str, data_object: dict[str, Any]):
    payload, signature = fake_billing.signed_event(
        event_id=event_id, event_type=event_type, data_object=data_object
    )
    return await client.post(WEBHOOK, content=payload, headers={"stripe-signature": signature})


def _purchase(
    session_id: str = "cs_top_up_1",
    paid_at: datetime = _utc(2026, 10, 3, 8),
    reversed: bool = False,
    charge_id: Optional[str] = "ch_1",
) -> TopUpPurchase:
    return TopUpPurchase(
        checkout_session_id=session_id, paid_at=paid_at, reversed=reversed, charge_id=charge_id
    )


async def _top_ups(client) -> list[dict[str, Any]]:
    return (await client.get(USAGE)).json()["allowance"]["top_ups"]


async def test_a_paid_up_user_buys_a_top_up_through_a_payment_checkout(
    client, db, user, subscribed, fake_billing, sells_top_ups
):
    response = await client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)

    assert response.status_code == 200
    assert response.json() == {"url": fake_billing.checkout_url, "session_id": "cs_top_up_fake_1"}
    assert fake_billing.top_up_checkouts == [
        TopUpCheckoutCall(customer_id="cus_fake_1", price_id="price_top_up", user_id=user.id)
    ]


async def test_a_top_up_checkout_records_the_acceptance_of_the_terms_before_stripe(
    client, db, user, subscribed, fake_billing, sells_top_ups
):
    fake_billing.fail_on = {"create_top_up_checkout"}

    response = await client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)

    assert response.status_code == 502
    [acceptance] = await _acceptances(db)
    assert (
        acceptance.user_id,
        acceptance.terms_version,
        acceptance.accepted_terms,
        acceptance.requested_immediate_start,
        acceptance.approved_specific_clauses,
    ) == (user.id, TERMS_VERSION, True, True, True)


async def test_a_top_up_checkout_without_the_terms_is_refused_before_stripe(
    client, db, subscribed, fake_billing, sells_top_ups
):
    response = await client.post(TOP_UP_CHECKOUT, json={**ACCEPTANCE, "accepted_terms": None})

    assert response.status_code == 422
    assert response.json()["detail"] == "Accept the Terms to buy a top-up."
    assert fake_billing.top_up_checkouts == [] and fake_billing.customers_created == []
    assert await _acceptances(db) == []


@pytest.mark.parametrize(
    ("status", "detail"),
    [
        ("trialing", "You can buy a top-up once your trial ends."),
        ("past_due", "Update your payment method to buy a top-up."),
        ("canceled", "Top-ups are for paid subscriptions. Subscribe to buy one."),
    ],
)
async def test_only_a_paid_up_subscription_may_buy_a_top_up(
    client, db, subscribed, fake_billing, sells_top_ups, status, detail
):
    await _set_status(db, subscribed, status)

    response = await client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)

    assert response.status_code == 409
    assert response.json() == {"detail": detail, "url": "http://localhost:5173/settings"}
    assert fake_billing.top_up_checkouts == []
    assert await _acceptances(db) == []


async def test_without_a_top_up_price_setting_no_top_ups_are_sold(client, subscribed, fake_billing):
    response = await client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)

    assert response.status_code == 404
    assert (await client.get(PLANS)).json()["top_up"] is None
    assert (await client.get(USAGE)).json()["allowance"]["may_buy_top_up"] is False


async def test_a_top_up_price_stripe_does_not_know_fails_the_checkout_with_502(
    client, subscribed, fake_billing, sells_top_ups
):
    fake_billing.prices = []

    response = await client.post(TOP_UP_CHECKOUT, json=ACCEPTANCE)

    assert response.status_code == 502
    assert fake_billing.top_up_checkouts == []


async def test_the_plans_offer_the_top_up_with_its_price_and_half_of_each_cap(
    client, fake_billing, sells_top_ups
):
    response = await client.get(PLANS)

    assert response.json()["top_up"] == {
        "amount": 1000,
        "currency": "eur",
        "generations": 250,
        "x_posts": 50,
        "link_x_posts": 5,
    }


async def test_a_top_up_of_a_small_cap_rounds_down_to_zero(
    client, fake_billing, sells_top_ups, monkeypatch
):
    monkeypatch.setattr(settings, "X_LINK_POSTS_MONTHLY_CAP", 1)
    monkeypatch.setattr(settings, "X_POSTS_MONTHLY_CAP", 0)

    top_up = (await client.get(PLANS)).json()["top_up"]

    assert (top_up["x_posts"], top_up["link_x_posts"]) == (0, 0)


async def test_a_completed_top_up_checkout_adds_the_top_up_for_12_months(
    client, db, subscribed, stripe_customer, fake_billing, sells_top_ups, fixed_clock
):
    fake_billing.set_top_up(stripe_customer, _purchase(paid_at=_utc(2026, 10, 3, 8)))

    response = await _send(
        client, fake_billing, "evt_1", "checkout.session.completed", {"customer": stripe_customer}
    )

    assert response.status_code == 200
    assert await _top_ups(client) == [
        {
            "generations_left": 250,
            "x_posts_left": 50,
            "link_x_posts_left": 5,
            "expires_at": "2027-10-03T08:00:00Z",
        }
    ]


async def test_a_top_up_adds_none_of_a_small_cap_and_no_number_for_a_count_with_no_cap(
    client, db, subscribed, stripe_customer, fake_billing, sells_top_ups, fixed_clock, monkeypatch
):
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", None)
    monkeypatch.setattr(settings, "X_LINK_POSTS_MONTHLY_CAP", 1)
    fake_billing.set_top_up(stripe_customer, _purchase())

    await _send(client, fake_billing, "evt_1", "checkout.session.completed", {"customer": "cus_1"})

    [top_up] = await _top_ups(client)
    assert (top_up["generations_left"], top_up["x_posts_left"], top_up["link_x_posts_left"]) == (
        None,
        50,
        0,
    )


async def test_a_replayed_sync_adds_each_top_up_once(
    client, db, subscribed, stripe_customer, fake_billing, sells_top_ups, fixed_clock
):
    fake_billing.set_top_up(stripe_customer, _purchase())
    for event_id in ("evt_1", "evt_2"):
        await _send(
            client, fake_billing, event_id, "checkout.session.completed", {"customer": "cus_1"}
        )

    assert len(await _top_ups(client)) == 1


async def test_a_refund_removes_what_is_left_of_the_top_up(
    client, db, subscribed, stripe_customer, fake_billing, sells_top_ups, fixed_clock
):
    fake_billing.set_top_up(stripe_customer, _purchase())
    await _send(client, fake_billing, "evt_1", "checkout.session.completed", {"customer": "cus_1"})
    fake_billing.set_top_up(stripe_customer, _purchase(reversed=True))

    response = await _send(
        client, fake_billing, "evt_2", "charge.refunded", {"id": "ch_1", "customer": "cus_1"}
    )

    assert response.status_code == 200
    assert await _top_ups(client) == []


async def test_a_dispute_removes_what_is_left_of_the_top_up(
    client, db, subscribed, stripe_customer, fake_billing, sells_top_ups, fixed_clock
):
    fake_billing.set_top_up(stripe_customer, _purchase())
    await _send(client, fake_billing, "evt_1", "checkout.session.completed", {"customer": "cus_1"})
    fake_billing.set_top_up(stripe_customer, _purchase(reversed=True))

    # A dispute names its charge, not the customer.
    response = await _send(
        client, fake_billing, "evt_2", "charge.dispute.created", {"id": "dp_1", "charge": "ch_1"}
    )

    assert response.status_code == 200
    assert await _top_ups(client) == []


async def test_a_top_up_refunded_before_its_first_sync_is_never_spendable(
    client, db, subscribed, stripe_customer, fake_billing, sells_top_ups, fixed_clock
):
    fake_billing.set_top_up(stripe_customer, _purchase(reversed=True))

    await _send(client, fake_billing, "evt_1", "charge.refunded", {"customer": "cus_1"})

    assert await _top_ups(client) == []


async def test_a_paid_top_up_first_synced_sends_top_up_added(
    client, subscribed, stripe_customer, fake_billing, sells_top_ups, fixed_clock, analytics
):
    fake_billing.set_top_up(stripe_customer, _purchase())

    await _send(client, fake_billing, "evt_1", "checkout.session.completed", {"customer": "cus_1"})

    analytics.capture.assert_called_once_with("top_up_added", distinct_id=subscribed.user_id)


@pytest.mark.parametrize("paid_at", [_utc(2025, 10, 3, 8), _utc(2025, 10, 10, 12, 0, 30)])
async def test_a_top_up_expired_before_its_first_sync_sends_no_top_up_added(
    client,
    subscribed,
    stripe_customer,
    fake_billing,
    sells_top_ups,
    fixed_clock,
    analytics,
    paid_at,
):
    fake_billing.set_top_up(stripe_customer, _purchase(paid_at=paid_at))

    response = await _send(
        client, fake_billing, "evt_1", "checkout.session.completed", {"customer": "cus_1"}
    )

    assert response.status_code == 200
    analytics.capture.assert_not_called()


async def test_a_top_up_refunded_before_its_first_sync_sends_no_top_up_added(
    client, subscribed, stripe_customer, fake_billing, sells_top_ups, fixed_clock, analytics
):
    fake_billing.set_top_up(stripe_customer, _purchase(reversed=True))

    response = await _send(client, fake_billing, "evt_1", "charge.refunded", {"customer": "cus_1"})

    assert response.status_code == 200
    analytics.capture.assert_not_called()


async def test_a_failed_top_up_sync_rolls_back_for_stripe_to_retry(
    client, db, subscribed, stripe_customer, fake_billing, sells_top_ups, fixed_clock
):
    fake_billing.set_top_up(stripe_customer, _purchase())
    fake_billing.fail_on = {"list_top_ups"}

    response = await _send(
        client, fake_billing, "evt_1", "checkout.session.completed", {"customer": "cus_1"}
    )

    assert response.status_code == 502
    fake_billing.fail_on = set()
    assert await _top_ups(client) == []


async def test_an_expired_top_up_is_not_listed(
    client, db, subscribed, stripe_customer, fake_billing, sells_top_ups, fixed_clock
):
    fake_billing.set_top_up(stripe_customer, _purchase(paid_at=_utc(2025, 10, 10, 12)))

    await _send(client, fake_billing, "evt_1", "checkout.session.completed", {"customer": "cus_1"})

    assert await _top_ups(client) == []


@pytest.mark.parametrize(("status", "may_buy"), [("active", True), ("past_due", False)])
async def test_usage_says_whether_the_user_may_buy_a_top_up(
    client, db, subscribed, fake_billing, sells_top_ups, status, may_buy
):
    await _set_status(db, subscribed, status)

    allowance = (await client.get(USAGE)).json()["allowance"]

    assert allowance["may_buy_top_up"] is may_buy
