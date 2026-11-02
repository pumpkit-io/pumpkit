"""
The Paywall on the backend (ADR 0018): on an Instance that sells Plans, every area route refuses a
User who isn't Subscribed, reads included, except auth, their own account, billing, `/instance`,
the legal pages, the Onboarding state, and reading or denying an app's connection request.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete

from pumpkit.billing.models import Subscription

SUBSCRIPTION_NEEDED = "This needs a subscription. Subscribe to continue."

GATED_ROUTES = [
    ("GET", "/api/v1/inspiration-authors"),
    ("GET", "/api/v1/x-connection"),
    ("DELETE", "/api/v1/x-connection"),
    ("POST", "/api/v1/x-connection/photo/use"),
    ("POST", "/api/v1/x-connection/photo/decline"),
    ("GET", "/api/v1/api-keys"),
    ("DELETE", "/api/v1/api-keys/key_unknown"),
    ("POST", "/api/v1/oauth/authorizations/request_unknown/approve"),
    ("GET", "/api/v1/posts"),
    ("GET", "/api/v1/posts/post_unknown"),
    ("GET", "/api/v1/scheduled-posts/communities"),
    ("GET", "/api/v1/usage"),
]

# The gated routes a new User, with nothing stored yet, reads successfully.
READS_OF_NOTHING_YET = [
    ("GET", "/api/v1/inspiration-authors"),
    ("GET", "/api/v1/api-keys"),
    ("GET", "/api/v1/posts"),
    ("GET", "/api/v1/scheduled-posts/communities"),
    ("GET", "/api/v1/usage"),
]

OPEN_ROUTES = [
    ("GET", "/api/v1/users/me"),
    ("GET", "/api/v1/billing/me"),
    ("GET", "/api/v1/billing/plans"),
    ("GET", "/api/v1/instance"),
    ("GET", "/api/v1/onboarding"),
]


async def _hold(db, user, status: str) -> None:
    db.add(
        Subscription(
            user_id=user.id,
            stripe_subscription_id=f"sub_{status}",
            stripe_customer_id="cus_paywall",
            status=status,
            stripe_created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    )
    await db.commit()


@pytest.mark.parametrize(("method", "path"), GATED_ROUTES)
async def test_a_user_who_isnt_subscribed_is_refused_every_gated_route(client, method, path):
    response = await client.request(method, path)

    assert response.status_code == 403
    assert response.json()["detail"] == SUBSCRIPTION_NEEDED


@pytest.mark.parametrize(("method", "path"), GATED_ROUTES)
async def test_a_user_whose_first_payment_is_still_processing_is_refused(
    client, db, user, method, path
):
    await _hold(db, user, "incomplete")

    response = await client.request(method, path)

    assert response.status_code == 403


@pytest.mark.parametrize(("method", "path"), GATED_ROUTES)
async def test_a_user_whose_subscription_ended_is_refused(client, db, subscribed, method, path):
    await db.execute(delete(Subscription))
    await db.commit()

    response = await client.request(method, path)

    assert response.status_code == 403


async def test_a_user_behind_on_payment_still_reads(client, db, user):
    await _hold(db, user, "past_due")

    response = await client.get("/api/v1/inspiration-authors")

    assert response.status_code == 200


@pytest.mark.parametrize(("method", "path"), OPEN_ROUTES)
async def test_a_user_who_isnt_subscribed_reaches_their_account_billing_and_the_instance(
    client, method, path
):
    response = await client.request(method, path)

    assert response.status_code == 200


async def test_a_user_who_isnt_subscribed_can_sign_out(client):
    response = await client.post("/api/v1/logout")

    assert response.status_code == 200


@pytest.mark.parametrize(("method", "path"), READS_OF_NOTHING_YET)
async def test_an_instance_that_sells_no_plans_gates_nothing(client, sells_no_plans, method, path):
    response = await client.request(method, path)

    assert response.status_code == 200
