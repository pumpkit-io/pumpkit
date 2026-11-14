"""Reading what Feedback wrote, for tests whose background tasks run inside the request."""

POSTS = "/api/v1/posts"


async def _versions(client, post_id: str) -> list[dict]:
    response = await client.get(f"{POSTS}/{post_id}")
    assert response.status_code == 200, response.text
    return response.json()["versions"]


async def latest_version(client, post_id: str) -> dict:
    """The Post's latest Version, which a Feedback the request wrote has made by now."""
    return (await _versions(client, post_id))[-1]


async def written_version(client, post_id: str, feedback: str, **body) -> dict:
    """Give Feedback, which must be accepted and write a Version, and return that Version."""
    before = len(await _versions(client, post_id))
    response = await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": feedback, **body})
    assert response.status_code == 202, response.text
    versions = await _versions(client, post_id)
    assert len(versions) == before + 1, "the Feedback wrote no Version"
    return versions[-1]
