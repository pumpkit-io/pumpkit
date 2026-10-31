"""`GET /onboarding`: where the web app sends a signed-in User next (ADR 0018)."""

from sqlalchemy import delete

from pumpkit.billing.models import Subscription

ONBOARDING = "/api/v1/onboarding"


async def test_a_user_who_isnt_subscribed_is_sent_to_the_paywall(client):
    response = await client.get(ONBOARDING)

    assert response.status_code == 200
    assert response.json() == {"next_step": "paywall"}


async def test_a_subscribed_user_has_no_next_step(client, subscribed):
    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": None}


async def test_the_paywall_comes_back_when_the_subscription_ends(client, db, subscribed):
    await db.execute(delete(Subscription))
    await db.commit()

    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "paywall"}


async def test_an_instance_that_sells_no_plans_has_no_paywall(client, sells_no_plans):
    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": None}


async def test_a_signed_out_visitor_is_refused(new_browser):
    response = await new_browser().get(ONBOARDING)

    assert response.status_code == 401
