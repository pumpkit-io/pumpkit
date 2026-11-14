"""`GET /onboarding` and `POST /onboarding/finish`: where the web app sends a signed-in User next."""

from datetime import datetime, timezone

from sqlalchemy import delete

from pumpkit.billing.models import Subscription
from pumpkit.onboarding.models import OnboardingFinish
from tests.positioning.positioning import DRAFT, DRAFTED, save_positioning

ONBOARDING = "/api/v1/onboarding"
FINISH = "/api/v1/onboarding/finish"


async def test_a_user_who_isnt_subscribed_is_sent_to_the_paywall(client):
    response = await client.get(ONBOARDING)

    assert response.status_code == 200
    assert response.json() == {"next_step": "paywall"}


async def test_a_subscribed_user_who_hasnt_finished_is_sent_to_the_persona_step(client, subscribed):
    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "persona"}


async def test_the_persona_step_is_done_once_a_positioning_is_saved(client, subscribed):
    await save_positioning(client)

    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": None}


async def test_a_draft_alone_does_not_finish_the_persona_step(
    client, subscribed, connect_x, fake_x_publisher, fake_x_reader, fake_llm
):
    await connect_x()
    fake_x_reader.user_ids[fake_x_publisher.account.user_id] = "ada"
    fake_x_reader.posts["ada"] = []
    fake_llm.replies = [{"positioning": DRAFTED}]
    assert (await client.post(DRAFT)).status_code == 200

    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "persona"}


async def test_an_instance_that_sells_no_plans_starts_at_the_persona_step(client, sells_no_plans):
    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "persona"}


async def test_finishing_opens_pumpkit(client, subscribed):
    await save_positioning(client)

    response = await client.post(FINISH)

    assert response.status_code == 204
    assert (await client.get(ONBOARDING)).json() == {"next_step": None}


async def test_finishing_twice_is_the_same_as_once(client, subscribed):
    await save_positioning(client)
    await client.post(FINISH)

    response = await client.post(FINISH)

    assert response.status_code == 204
    assert (await client.get(ONBOARDING)).json() == {"next_step": None}


async def test_finishing_without_a_positioning_is_refused(client, subscribed):
    response = await client.post(FINISH)

    assert response.status_code == 409
    assert response.json()["detail"] == "Write your positioning to continue."
    assert (await client.get(ONBOARDING)).json() == {"next_step": "persona"}


async def test_finishing_needs_a_subscription(client):
    response = await client.post(FINISH)

    assert response.status_code == 403


async def test_a_user_who_finished_before_positionings_existed_stays_finished(
    client, db, user, subscribed
):
    db.add(
        OnboardingFinish(user_id=user.id, finished_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
    )
    await db.commit()

    assert (await client.get(ONBOARDING)).json() == {"next_step": None}


async def test_a_finished_user_whose_subscription_ended_sees_only_the_paywall(
    client, db, user, subscribed
):
    await save_positioning(client)
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


async def test_a_user_at_the_paywall_gets_no_draft_and_x_is_not_read(
    client, connect_x, fake_x_publisher, fake_x_reader, fake_llm
):
    await connect_x()
    fake_x_reader.user_ids[fake_x_publisher.account.user_id] = "ada"
    assert (await client.get(ONBOARDING)).json() == {"next_step": "paywall"}

    response = await client.post(DRAFT)

    assert response.status_code == 403
    assert fake_x_reader.user_id_calls == []
    assert fake_llm.calls == []


async def test_a_signed_out_visitor_is_refused(new_browser):
    response = await new_browser().get(ONBOARDING)

    assert response.status_code == 401


async def test_a_subscribed_user_without_publishing_permission_is_sent_to_persona(
    client, subscribed, x_configured
):
    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "persona"}


async def test_a_user_who_connected_x_moves_on_to_the_persona_step(
    client, subscribed, x_configured, connect_x
):
    await connect_x()

    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "persona"}


async def test_the_paywall_comes_before_the_x_step(client, x_configured):
    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "paywall"}


async def test_an_instance_that_sells_no_plans_starts_directly_at_persona(
    client, sells_no_plans, x_configured
):
    response = await client.get(ONBOARDING)

    assert response.json() == {"next_step": "persona"}


async def test_finishing_does_not_require_publishing_permission(client, subscribed, x_configured):
    await save_positioning(client)

    response = await client.post(FINISH)

    assert response.status_code == 204
    assert (await client.get(ONBOARDING)).json() == {"next_step": None}


async def test_finishing_after_connecting_x_opens_pumpkit(
    client, subscribed, x_configured, connect_x
):
    await connect_x()
    await save_positioning(client)

    response = await client.post(FINISH)

    assert response.status_code == 204
    assert (await client.get(ONBOARDING)).json() == {"next_step": None}


async def test_a_finished_user_stays_finished_when_disconnection_is_refused(
    client, subscribed, x_configured, connect_x
):
    await connect_x()
    await save_positioning(client)
    await client.post(FINISH)

    disconnected = await client.delete("/api/v1/x-connection")

    assert disconnected.status_code == 405
    assert (await client.get(ONBOARDING)).json() == {"next_step": None}
