"""Looking up a pasted Community's name through the HTTP API, and keeping it on a Scheduled post."""

import pytest

from pumpkit.scheduling.communities import NOT_A_COMMUNITY

LOOKUPS = "/api/v1/community-lookups"
COMMUNITY_ID = "1493446837214187523"
COMMUNITY_URL = f"https://x.com/i/communities/{COMMUNITY_ID}"


@pytest.mark.parametrize(
    "pasted", [COMMUNITY_URL, f"https://twitter.com/i/communities/{COMMUNITY_ID}/", COMMUNITY_ID]
)
async def test_a_pasted_community_comes_back_with_its_name(
    client, subscribed, fake_x_reader, pasted
):
    fake_x_reader.communities[COMMUNITY_ID] = "Build in Public"

    response = await client.post(LOOKUPS, json={"pasted": pasted})

    assert response.status_code == 200, response.text
    assert response.json() == {"id": COMMUNITY_ID, "name": "Build in Public", "url": COMMUNITY_URL}
    assert fake_x_reader.community_calls == [COMMUNITY_ID]


async def test_text_that_is_not_a_community_is_refused_without_a_lookup(
    client, subscribed, fake_x_reader
):
    response = await client.post(LOOKUPS, json={"pasted": "https://x.com/levelsio"})

    assert response.status_code == 422
    assert response.json()["detail"] == NOT_A_COMMUNITY
    assert fake_x_reader.community_calls == []


async def test_a_community_x_does_not_have_is_refused(client, subscribed, fake_x_reader):
    response = await client.post(LOOKUPS, json={"pasted": COMMUNITY_ID})

    assert response.status_code == 404
    assert response.json()["detail"] == "X has no Community with that ID. Check the URL."


@pytest.mark.parametrize("failure", ["not_configured", "fail"])
async def test_without_twitterapi_io_the_community_comes_back_without_a_name(
    client, subscribed, fake_x_reader, failure
):
    setattr(fake_x_reader, failure, True)

    response = await client.post(LOOKUPS, json={"pasted": COMMUNITY_URL})

    assert response.status_code == 200, response.text
    assert response.json() == {"id": COMMUNITY_ID, "name": None, "url": COMMUNITY_URL}


async def test_lookups_are_rate_limited(client, subscribed, fake_x_reader):
    for _ in range(10):
        await client.post(LOOKUPS, json={"pasted": COMMUNITY_ID})

    response = await client.post(LOOKUPS, json={"pasted": COMMUNITY_ID})

    assert response.status_code == 429
