import stripe

import app.api.mediators.stripe as stripe_mediator


async def test_list_prices_parses_stripe_objects(monkeypatch):
    price = stripe.Price.construct_from(
        {
            "id": "price_1",
            "currency": "usd",
            "unit_amount": 500,
            "recurring": {"interval": "month", "interval_count": 1},
            "product": {"id": "prod_1", "name": "Pro", "description": "d"},
        },
        "sk_test",
    )
    monkeypatch.setattr(
        stripe.Price,
        "list",
        lambda **_: stripe.ListObject.construct_from({"data": [price]}, "sk_test"),
    )

    result = await stripe_mediator.list_prices()

    assert result.data[0].id == "price_1"
    assert result.data[0].product.name == "Pro"
    assert result.data[0].recurring.interval == "month"
