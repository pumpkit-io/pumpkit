from typing import Any

POSITIONING = "/api/v1/positioning"
TEXT = "I'm a solo founder. I post about bootstrapping for people starting their first SaaS."
START_DRAFT = "/api/v1/positioning/draft/start"
DRAFTED = (
    "I'm a solo founder building a pricing tool. I post about pricing and bootstrapping "
    "for people starting their first SaaS. I post to earn sign-ups for ada.dev."
)


async def save_positioning(client) -> None:
    """Give the User `client` signs requests as a Positioning, which writing a Post needs."""
    assert (await client.put(POSITIONING, json={"text": TEXT})).status_code == 200


async def positioning_draft(client) -> Any:
    """The Positioning draft `GET /positioning` answers for `client`, or None."""
    response = await client.get(POSITIONING)
    assert response.status_code == 200, response.text
    return response.json()["draft"]
