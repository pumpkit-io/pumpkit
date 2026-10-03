import stripe
from sqlalchemy import select

import app.api.mediators.stripe as stripe_mediator
from app.db.models import Subscription
from app.schemas.stripe import TrialRequest


async def test_start_trial_handles_stripe_object(db, user, monkeypatch):
    created = stripe.Subscription.construct_from(
        {
            "id": "sub_trial",
            "object": "subscription",
            "customer": "cus_1",
            "status": "trialing",
            "trial_end": 1_900_000_000,
            "cancel_at_period_end": False,
            "items": {
                "object": "list",
                "data": [
                    {
                        "id": "si_1",
                        "price": {"id": "price_trial"},
                        "current_period_end": 1_900_000_000,
                    }
                ],
            },
        },
        "sk_test",
    )
    monkeypatch.setattr(stripe.Subscription, "create", lambda **_: created)

    async def _ensure(db, user):
        return "cus_1"

    monkeypatch.setattr(stripe_mediator.stripe_customers_service, "ensure_stripe_customer", _ensure)

    result = await stripe_mediator.start_trial(
        db=db, user=user, trial_request=TrialRequest(price_id="price_trial", trial_period_days=7)
    )

    assert result.subscription_id == "sub_trial"
    assert result.status == "trialing"
    assert result.trial_end is not None
    sub = (await db.execute(select(Subscription))).scalar_one()
    assert sub.stripe_subscription_id == "sub_trial"
    assert sub.stripe_price_id == "price_trial"
    assert sub.stripe_customer_id == "cus_1"
    assert sub.current_period_end is not None
