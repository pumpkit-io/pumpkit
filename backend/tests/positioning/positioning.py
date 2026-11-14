POSITIONING = "/api/v1/positioning"
TEXT = "I'm a solo founder. I post about bootstrapping for people starting their first SaaS."
DRAFT = "/api/v1/positioning/draft"
DRAFTED = (
    "I'm a solo founder building a pricing tool. I post about pricing and bootstrapping "
    "for people starting their first SaaS. I post to earn sign-ups for ada.dev."
)


async def save_positioning(client) -> None:
    """Give the User `client` signs requests as a Positioning, which writing a Post needs."""
    assert (await client.put(POSITIONING, json={"text": TEXT})).status_code == 200
