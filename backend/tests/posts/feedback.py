"""Reading what Feedback wrote, for tests whose background tasks run inside the request."""

POSTS = "/api/v1/posts"


async def latest_version(client, post_id: str) -> dict:
    """The Post's latest Version, which a Feedback the request wrote has made by now."""
    response = await client.get(f"{POSTS}/{post_id}")
    assert response.status_code == 200, response.text
    return response.json()["versions"][-1]


async def written_version(client, post_id: str, feedback: str, **body) -> dict:
    """Give Feedback, which must be accepted, and return the Version it wrote."""
    response = await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": feedback, **body})
    assert response.status_code == 202, response.text
    return await latest_version(client, post_id)
