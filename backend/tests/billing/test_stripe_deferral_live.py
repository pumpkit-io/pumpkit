"""Opt-in provider experiment; ordinary test runs never contact Stripe."""

import os
import time
from datetime import datetime, timezone
from typing import Any

import pytest
import stripe

from pumpkit.billing.gateway import DeferralRefused, StripeBillingGateway

KEY = os.environ.get("PUMPKIT_STRIPE_TEST_KEY", "")
pytestmark = pytest.mark.skipif(not KEY, reason="requires explicit Stripe test-mode credential")
START = 1832932800  # 2028-01-31 12:00 UTC exercises leap-day monthly renewal.


def timestamp(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


@pytest.fixture(scope="module")
def provider():
    if not KEY.startswith(("sk_test_", "rk_test_")):
        pytest.fail("Only Stripe test-mode credentials are accepted")
    client = stripe.StripeClient(KEY, max_network_retries=0)
    assert client.v1.balance.retrieve().livemode is False
    product = client.v1.products.create({"name": "Pumpkit #394 isolated verification"})
    prices = {}
    try:
        for interval, amount in [("month", 1000), ("year", 10000)]:
            prices[interval] = client.v1.prices.create(
                {
                    "product": product.id,
                    "currency": "usd",
                    "unit_amount": amount,
                    "recurring": {"interval": interval},
                }
            ).id
        yield client, product.id, prices
    finally:
        for price in prices.values():
            client.v1.prices.update(price, {"active": False})
        client.v1.products.update(product.id, {"active": False})


@pytest.fixture
def scenario(provider):
    client, _, prices = provider
    clock = client.v1.test_helpers.test_clocks.create({"frozen_time": START, "name": "pumpkit-394"})
    try:
        customer = client.v1.customers.create(
            {"test_clock": clock.id, "name": "Synthetic coupon verification"}
        )
        payment_method = client.v1.payment_methods.attach("pm_card_visa", {"customer": customer.id})

        def create(mode: str, interval: str = "month", payment: bool = True, **extra: Any):
            return client.v1.subscriptions.create(
                {
                    "customer": customer.id,
                    "items": [{"price": prices[interval]}],
                    **({"default_payment_method": payment_method.id} if payment else {}),
                    "billing_mode": {"type": mode},
                    **extra,
                }
            ).to_dict()

        def advance(target: int):
            client.v1.test_helpers.test_clocks.advance(clock.id, {"frozen_time": target})
            for _ in range(90):
                if client.v1.test_helpers.test_clocks.retrieve(clock.id).status == "ready":
                    return
                time.sleep(1)
            pytest.fail("Stripe test clock did not become ready within 90 seconds")

        def invoices():
            return [
                {"amount_due": i.amount_due, "status": i.status}
                for i in client.v1.invoices.list({"customer": customer.id, "limit": 100}).data
            ]

        yield client, create, advance, invoices
    finally:
        client.v1.test_helpers.test_clocks.delete(clock.id)


@pytest.mark.parametrize("mode", ["classic", "flexible"])
@pytest.mark.parametrize(
    "interval,paid_end,free_end,next_end,amount",
    [
        ("month", "2028-02-29T12:00", "2028-04-30T12:00", "2028-05-30T12:00", 1000),
        ("year", "2029-01-31T12:00", "2029-03-31T12:00", "2030-03-31T12:00", 10000),
    ],
)
def test_paid_deferral_resumes_full_interval(
    scenario, mode, interval, paid_end, free_end, next_end, amount
):
    client, create, advance, invoices = scenario
    subscription = create(mode, interval)
    assert subscription["items"]["data"][0]["current_period_end"] == timestamp(paid_end)
    before = invoices()
    assert before == [{"amount_due": amount, "status": "paid"}]
    updated = client.v1.subscriptions.update(
        subscription["id"], {"trial_end": timestamp(free_end), "proration_behavior": "none"}
    ).to_dict()
    assert updated["status"] == "trialing"
    assert updated["trial_end"] == timestamp(free_end)
    assert updated["billing_cycle_anchor"] == timestamp(free_end)
    assert [i for i in invoices() if i["amount_due"] != 0] == before
    # Clock advances are bounded by twice the shortest subscription interval.
    current = START
    while current < timestamp(free_end) + 3600:
        current = min(current + 28 * 86400, timestamp(free_end) + 3600)
        advance(current)
    renewed = client.v1.subscriptions.retrieve(subscription["id"]).to_dict()
    assert renewed["status"] == "active"
    item = renewed["items"]["data"][0]
    assert item["current_period_start"] == timestamp(free_end)
    assert item["current_period_end"] == timestamp(next_end)
    assert [i for i in invoices() if i["amount_due"] != 0] == [
        {"amount_due": amount, "status": "paid"},
        {"amount_due": amount, "status": "paid"},
    ]


@pytest.mark.parametrize("mode", ["classic", "flexible"])
def test_repeated_trial_deferral_and_future_price_change(scenario, provider, mode):
    client, create, advance, invoices = scenario
    _, _, prices = provider
    subscription = create(mode, trial_end=timestamp("2028-02-07T12:00"))
    updated = subscription
    for end in ["2028-03-07T12:00", "2028-04-07T12:00"]:
        updated = client.v1.subscriptions.update(
            subscription["id"], {"trial_end": timestamp(end), "proration_behavior": "none"}
        ).to_dict()
        assert updated["trial_end"] == timestamp(end)
        assert all(i["amount_due"] == 0 for i in invoices())
    changed = client.v1.subscriptions.update(
        subscription["id"],
        {
            "items": [{"id": updated["items"]["data"][0]["id"], "price": prices["year"]}],
            "proration_behavior": "none",
        },
    ).to_dict()
    assert changed["trial_end"] == timestamp("2028-04-07T12:00")
    assert changed["status"] == "trialing"
    assert all(i["amount_due"] == 0 for i in invoices())
    advance(timestamp("2028-03-01T12:00"))
    advance(timestamp("2028-04-07T13:00"))
    renewed = client.v1.subscriptions.retrieve(subscription["id"]).to_dict()
    assert renewed["status"] == "active"
    assert renewed["items"]["data"][0]["current_period_end"] == timestamp("2029-04-07T12:00")
    assert invoices()[0] == {"amount_due": 10000, "status": "paid"}


@pytest.mark.parametrize("mode", ["classic", "flexible"])
@pytest.mark.parametrize("cancel_before", [False, True])
def test_cancellation_preserved_before_and_during_deferral(scenario, mode, cancel_before):
    client, create, advance, invoices = scenario
    subscription = (
        create(mode) if cancel_before else create(mode, trial_end=timestamp("2028-03-31T12:00"))
    )
    if cancel_before:
        client.v1.subscriptions.update(subscription["id"], {"cancel_at_period_end": True})
        client.v1.subscriptions.update(
            subscription["id"],
            {"trial_end": timestamp("2028-03-31T12:00"), "proration_behavior": "none"},
        )
    updated = (
        client.v1.subscriptions.retrieve(subscription["id"])
        if cancel_before
        else client.v1.subscriptions.update(subscription["id"], {"cancel_at_period_end": True})
    ).to_dict()
    assert updated["cancel_at_period_end"] is True
    assert updated["cancel_at"] == timestamp("2028-03-31T12:00")
    advance(timestamp("2028-03-01T12:00"))
    advance(timestamp("2028-03-31T13:00"))
    assert client.v1.subscriptions.retrieve(subscription["id"]).status == "canceled"
    assert [i for i in invoices() if i["amount_due"] != 0] == (
        [{"amount_due": 1000, "status": "paid"}] if cancel_before else []
    )


@pytest.mark.parametrize("mode", ["classic", "flexible"])
def test_cardless_future_signup_cancels_without_payment(scenario, mode):
    client, create, advance, invoices = scenario
    subscription = create(
        mode,
        payment=False,
        trial_end=timestamp("2028-03-31T12:00"),
        trial_settings={"end_behavior": {"missing_payment_method": "cancel"}},
    )
    assert subscription["default_payment_method"] is None
    assert subscription["status"] == "trialing"
    advance(timestamp("2028-03-01T12:00"))
    advance(timestamp("2028-03-31T13:00"))
    assert client.v1.subscriptions.retrieve(subscription["id"]).status == "canceled"
    assert all(i["amount_due"] == 0 for i in invoices())


@pytest.mark.parametrize("mode", ["classic", "flexible"])
def test_exact_provider_horizon(scenario, mode):
    client, create, advance, invoices = scenario
    subscription = create(mode)
    maximum = START + 730 * 86400
    updated = client.v1.subscriptions.update(
        subscription["id"], {"trial_end": maximum, "proration_behavior": "none"}
    ).to_dict()
    assert updated["trial_end"] == maximum
    with pytest.raises(stripe.InvalidRequestError):
        client.v1.subscriptions.update(
            subscription["id"], {"trial_end": maximum + 1, "proration_behavior": "none"}
        )
    assert client.v1.subscriptions.retrieve(subscription["id"]).trial_end == maximum
    advance(START + 86400)
    updated = client.v1.subscriptions.update(
        subscription["id"], {"trial_end": maximum + 86400, "proration_behavior": "none"}
    ).to_dict()
    assert updated["trial_end"] == maximum + 86400
    with pytest.raises(stripe.InvalidRequestError):
        client.v1.subscriptions.update(
            subscription["id"], {"trial_end": maximum + 86401, "proration_behavior": "none"}
        )
    assert [i for i in invoices() if i["amount_due"] != 0] == [
        {"amount_due": 1000, "status": "paid"}
    ]


@pytest.mark.parametrize("mode", ["classic", "flexible"])
async def test_subscribe_now_would_charge_away_free_time(scenario, mode):
    client, create, _, invoices = scenario
    subscription = create(mode, trial_end=timestamp("2028-03-31T12:00"))
    await StripeBillingGateway(client).end_trial(subscription_id=subscription["id"])
    assert client.v1.subscriptions.retrieve(subscription["id"]).status == "active"
    assert invoices()[0] == {"amount_due": 1000, "status": "paid"}


@pytest.mark.parametrize("mode", ["classic", "flexible"])
@pytest.mark.parametrize("interval", ["month", "year"])
async def test_gateway_changes_deferred_interval(scenario, provider, mode, interval):
    client, create, _, invoices = scenario
    _, _, prices = provider
    subscription = create(mode, interval)
    gateway = StripeBillingGateway(client)
    end = datetime(2029, 3, 31, 12, tzinfo=timezone.utc)
    await gateway.defer_renewal(
        subscription_id=subscription["id"],
        target=end,
        operation_id=f"verify-deferral-{subscription['id']}",
    )
    before = client.v1.subscriptions.retrieve(subscription["id"]).to_dict()
    paid = [invoice for invoice in invoices() if invoice["amount_due"]]
    await gateway.change_plan(
        subscription_id=subscription["id"],
        item_id=before["items"]["data"][0]["id"],
        price_id=prices["month" if interval == "year" else "year"],
        operation_id=f"verify-interval-{subscription['id']}",
        first_payment_at=end,
    )
    changed = client.v1.subscriptions.retrieve(subscription["id"]).to_dict()
    assert changed["trial_end"] == before["trial_end"] == int(end.timestamp())
    assert changed["billing_cycle_anchor"] == before["billing_cycle_anchor"]
    assert changed["items"]["data"][0]["price"]["recurring"]["interval"] == (
        "month" if interval == "year" else "year"
    )
    assert [invoice for invoice in invoices() if invoice["amount_due"]] == paid


@pytest.mark.parametrize("mode", ["classic", "flexible"])
async def test_delayed_interval_change_cannot_restart_an_already_paid_period(
    scenario, provider, mode
):
    client, create, advance, invoices = scenario
    _, _, prices = provider
    end = timestamp("2028-02-07T12:00")
    subscription = create(mode, "year", trial_end=end)
    advance(end + 3600)
    before = client.v1.subscriptions.retrieve(subscription["id"]).to_dict()
    paid = invoices()
    assert before["status"] == "active"
    assert paid[0] == {"amount_due": 10000, "status": "paid"}
    with pytest.raises(DeferralRefused):
        await StripeBillingGateway(client).change_plan(
            subscription_id=subscription["id"],
            item_id=before["items"]["data"][0]["id"],
            price_id=prices["month"],
            operation_id=f"late-interval-{subscription['id']}",
            first_payment_at=datetime.fromtimestamp(end, timezone.utc),
        )
    after = client.v1.subscriptions.retrieve(subscription["id"]).to_dict()
    assert after["items"]["data"][0]["price"]["id"] == before["items"]["data"][0]["price"]["id"]
    assert (
        after["items"]["data"][0]["current_period_end"]
        == before["items"]["data"][0]["current_period_end"]
    )
    assert invoices() == paid


@pytest.mark.parametrize("mode", ["classic", "flexible"])
async def test_interval_change_one_second_before_payment_preserves_the_date(
    scenario, provider, mode
):
    client, create, advance, invoices = scenario
    _, _, prices = provider
    end = timestamp("2028-02-07T12:00")
    subscription = create(mode, "year", trial_end=end)
    advance(end - 1)
    before = client.v1.subscriptions.retrieve(subscription["id"]).to_dict()
    await StripeBillingGateway(client).change_plan(
        subscription_id=subscription["id"],
        item_id=before["items"]["data"][0]["id"],
        price_id=prices["month"],
        operation_id=f"last-second-interval-{subscription['id']}",
        first_payment_at=datetime.fromtimestamp(end, timezone.utc),
    )
    changed = client.v1.subscriptions.retrieve(subscription["id"]).to_dict()
    assert changed["trial_end"] == changed["billing_cycle_anchor"] == end
    assert all(invoice["amount_due"] == 0 for invoice in invoices())
    advance(end + 3600)
    paid = client.v1.subscriptions.retrieve(subscription["id"]).to_dict()
    assert paid["items"]["data"][0]["current_period_start"] == end
    assert paid["items"]["data"][0]["current_period_end"] == timestamp("2028-03-07T12:00")
    assert invoices()[0] == {"amount_due": 1000, "status": "paid"}
