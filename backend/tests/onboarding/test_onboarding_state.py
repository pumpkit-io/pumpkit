"""`GET /onboarding` and `POST /onboarding/finish`: where the web app sends a signed-in User next."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.billing.models import Subscription

ONBOARDING = "/api/v1/onboarding"
FINISH = "/api/v1/onboarding/finish"
AUTHORS = "/api/v1/inspiration-authors"


def _posts(*ids: str) -> list[FetchedPost]:
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return [
        FetchedPost(post_id=post_id, text=f"post {post_id}", posted_at=start - timedelta(hours=i))
        for i, post_id in enumerate(ids)
    ]


async def _add_author(client, fake_x_reader, handle: str = "levelsio") -> None:
    fake_x_reader.posts[handle] = _posts(f"{handle}_1", f"{handle}_2")
    response = await client.post(AUTHORS, json={"handle": handle})
    assert response.status_code == 201


async def test_a_user_who_isnt_subscribed_is_sent_to_the_paywall(client):
    response = await client.get(ONBOARDING)

    assert response.status_code == 200
    assert response.json() == {"next_step": "paywall"}


async def test_a_subscribed_user_who_hasnt_finished_is_sent_to_the_persona_step(client, subscribed):
    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "persona"}


async def test_the_persona_step_stays_until_continue_even_with_an_author(
    client, subscribed, fake_x_reader
):
    await _add_author(client, fake_x_reader)

    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "persona"}


async def test_an_instance_that_sells_no_plans_starts_at_the_persona_step(client, sells_no_plans):
    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "persona"}


async def test_finishing_opens_pumpkit(client, subscribed, fake_x_reader):
    await _add_author(client, fake_x_reader)

    response = await client.post(FINISH)

    assert response.status_code == 204
    assert (await client.get(ONBOARDING)).json() == {"next_step": None}


async def test_finishing_twice_is_the_same_as_once(client, subscribed, fake_x_reader):
    await _add_author(client, fake_x_reader)
    await client.post(FINISH)

    response = await client.post(FINISH)

    assert response.status_code == 204
    assert (await client.get(ONBOARDING)).json() == {"next_step": None}


async def test_finishing_with_an_empty_persona_is_refused(client, subscribed):
    response = await client.post(FINISH)

    assert response.status_code == 409
    assert response.json()["detail"] == "Pick at least one inspiration author to continue."
    assert (await client.get(ONBOARDING)).json() == {"next_step": "persona"}


async def test_finishing_needs_a_subscription(client):
    response = await client.post(FINISH)

    assert response.status_code == 403


async def test_a_finished_user_stays_finished_after_emptying_the_persona(
    client, subscribed, fake_x_reader
):
    await _add_author(client, fake_x_reader)
    await client.post(FINISH)

    await client.delete(f"{AUTHORS}/levelsio")

    assert (await client.get(ONBOARDING)).json() == {"next_step": None}


async def test_a_finished_user_whose_subscription_ended_sees_only_the_paywall(
    client, db, user, subscribed, fake_x_reader
):
    await _add_author(client, fake_x_reader)
    await client.post(FINISH)
    await db.execute(delete(Subscription))
    await db.commit()

    assert (await client.get(ONBOARDING)).json() == {"next_step": "paywall"}

    db.add(
        Subscription(
            user_id=user.id,
            stripe_subscription_id="sub_again",
            stripe_customer_id="cus_subscribed",
            status="active",
            stripe_created_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
        )
    )
    await db.commit()

    assert (await client.get(ONBOARDING)).json() == {"next_step": None}


async def test_a_signed_out_visitor_is_refused(new_browser):
    response = await new_browser().get(ONBOARDING)

    assert response.status_code == 401


async def test_a_subscribed_user_without_x_is_sent_to_the_x_step(client, subscribed, x_configured):
    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "x_connection"}


async def test_the_x_step_comes_before_the_persona_even_with_an_author(
    client, subscribed, x_configured, fake_x_reader
):
    await _add_author(client, fake_x_reader)

    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "x_connection"}


async def test_a_user_who_connected_x_moves_on_to_the_persona_step(
    client, subscribed, x_configured, connect_x
):
    await connect_x()

    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "persona"}


async def test_an_instance_without_x_skips_the_x_step(client, subscribed):
    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "persona"}


async def test_the_paywall_comes_before_the_x_step(client, x_configured):
    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "paywall"}


async def test_an_instance_that_sells_no_plans_starts_at_the_x_step(
    client, sells_no_plans, x_configured
):
    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "x_connection"}


async def test_finishing_without_x_is_refused_while_the_x_step_is_required(
    client, subscribed, x_configured, fake_x_reader
):
    await _add_author(client, fake_x_reader)

    response = await client.post(FINISH)

    assert response.status_code == 409
    assert response.json()["detail"] == "Connect your X account to continue."
    assert (await client.get(ONBOARDING)).json() == {"next_step": "x_connection"}


async def test_finishing_after_connecting_x_opens_pumpkit(
    client, subscribed, x_configured, connect_x, fake_x_reader
):
    await connect_x()
    await _add_author(client, fake_x_reader)

    response = await client.post(FINISH)

    assert response.status_code == 204
    assert (await client.get(ONBOARDING)).json() == {"next_step": None}


async def test_a_finished_user_stays_finished_after_disconnecting_x(
    client, subscribed, x_configured, connect_x, fake_x_reader
):
    await connect_x()
    await _add_author(client, fake_x_reader)
    await client.post(FINISH)

    disconnected = await client.delete("/api/v1/x-connection")

    assert disconnected.status_code == 204
    assert (await client.get(ONBOARDING)).json() == {"next_step": None}
