"""`GET /positioning` and `PUT /positioning`: the signed-in User's Positioning."""

from datetime import timedelta

import pytest

from tests.positioning.positioning import POSITIONING, TEXT


async def test_a_user_who_saved_nothing_reads_no_positioning(client, subscribed):
    response = await client.get(POSITIONING)

    assert response.status_code == 200
    assert response.json() == {"text": None, "saved_at": None}


async def test_saving_a_positioning_stores_it_with_when_it_was_saved(
    client, subscribed, fixed_clock
):
    response = await client.put(POSITIONING, json={"text": TEXT})

    assert response.status_code == 200
    assert response.json() == {"text": TEXT, "saved_at": "2026-10-10T12:00:30Z"}
    assert (await client.get(POSITIONING)).json() == response.json()


async def test_saving_again_replaces_the_positioning_and_its_time(client, subscribed, fixed_clock):
    await client.put(POSITIONING, json={"text": TEXT})
    fixed_clock.advance(timedelta(hours=1))

    response = await client.put(POSITIONING, json={"text": "I post about pricing now."})

    assert response.json() == {
        "text": "I post about pricing now.",
        "saved_at": "2026-10-10T13:00:30Z",
    }
    assert (await client.get(POSITIONING)).json() == response.json()


async def test_the_text_is_saved_without_the_space_around_it(client, subscribed):
    response = await client.put(POSITIONING, json={"text": f"\n  {TEXT}  \n"})

    assert response.json()["text"] == TEXT


@pytest.mark.parametrize("text", ["", "   \n\t "])
async def test_a_blank_positioning_is_refused_and_the_saved_one_kept(client, subscribed, text):
    await client.put(POSITIONING, json={"text": TEXT})

    response = await client.put(POSITIONING, json={"text": text})

    assert response.status_code == 422
    assert (await client.get(POSITIONING)).json()["text"] == TEXT


async def test_a_positioning_holds_up_to_4000_characters(client, subscribed):
    longest = "a" * 4000

    assert (await client.put(POSITIONING, json={"text": longest})).status_code == 200
    response = await client.put(POSITIONING, json={"text": longest + "a"})

    assert response.status_code == 422
    assert (await client.get(POSITIONING)).json()["text"] == longest


async def test_the_space_around_a_positioning_does_not_count_towards_its_length(client, subscribed):
    longest = "a" * 4000

    response = await client.put(POSITIONING, json={"text": f"  {longest}\n"})

    assert response.status_code == 200
    assert response.json()["text"] == longest


async def test_each_user_reads_and_saves_only_their_own_positioning(
    client, subscribed, sign_in_as_another_subscribed_user
):
    await client.put(POSITIONING, json={"text": TEXT})

    await sign_in_as_another_subscribed_user()

    assert (await client.get(POSITIONING)).json() == {"text": None, "saved_at": None}
    await client.put(POSITIONING, json={"text": "I'm Bob."})
    assert (await client.get(POSITIONING)).json()["text"] == "I'm Bob."
