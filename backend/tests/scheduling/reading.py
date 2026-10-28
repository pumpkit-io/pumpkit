"""
Reading the User's Scheduled posts back as the web app does, through each Post on `GET /posts`
and its `GET /posts/{id}`, for tests that check what a change left behind. MCP tests read them
the same way through `list_posts` and `get_post`.
"""

from httpx import AsyncClient

from pumpkit.auth.models import User
from pumpkit.scheduling import mediator
from pumpkit.scheduling.schemas import ScheduledPostResponse
from tests.mcp_client import McpClient

# The tabs holding a Post with a Scheduled post, in the order the old Scheduled page listed them.
STATUSES = ("scheduled", "published", "failed")


async def scheduled_posts(client: AsyncClient) -> list[dict]:
    """
    Every Scheduled post of the User in full: waiting ones soonest first, then Published ones
    most recently published first, then Failed ones most recently due first.
    """
    found = []
    for status in STATUSES:
        listed = await client.get("/api/v1/posts", params={"status": status, "limit": 50})
        assert listed.status_code == 200, listed.text
        for item in listed.json()["data"]:
            post = await client.get(f"/api/v1/posts/{item['id']}")
            assert post.status_code == 200, post.text
            found.append(post.json()["scheduled_post"])
    return found


async def scheduled_posts_through_the_mediator(db, user: User) -> list[ScheduledPostResponse]:
    """`scheduled_posts`, for tests that call the mediator without the API."""
    found = []
    for status in STATUSES:
        listed = await mediator.list_posts(db, user, status=status, limit=50, offset=0)
        for item in listed.data:
            post = await mediator.get_post(db, user, post_id=item.id)
            assert post.scheduled_post is not None
            found.append(post.scheduled_post)
    return found


async def scheduled_posts_through_mcp(mcp: McpClient) -> list[dict]:
    """`scheduled_posts`, as Claude Code reads them with `list_posts` and `get_post`."""
    found = []
    for status in STATUSES:
        listed = await mcp.call_tool("list_posts", status=status, limit=50)
        assert listed["isError"] is False, listed
        for item in listed["structuredContent"]["data"]:
            post = await mcp.call_tool("get_post", post_id=item["id"])
            assert post["isError"] is False, post
            found.append(post["structuredContent"]["scheduled_post"])
    return found
