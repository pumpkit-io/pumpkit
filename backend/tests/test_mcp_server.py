"""
The MCP endpoint: OAuth access token authentication (ADR 0020), the access gate and limits every
tool shares (ADR 0012).
"""

from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import MagicMock

from sqlalchemy import delete

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.billing.models import Subscription
from pumpkit.core.analytics import posthog_client
from tests.conftest import FIXED_NOW
from tests.mcp_client import MCP, McpClient, error_text

API_KEYS = "/api/v1/api-keys"
CONNECTIONS = "/api/v1/app-connections"


async def test_initialize_returns_the_server_instructions(subscribed, mcp):
    result = await mcp.initialize()

    assert result["serverInfo"]["name"] == "pumpkit"
    assert result["capabilities"]["tools"] is not None
    instructions = result["instructions"]
    for term in (
        "brief",
        "feedback",
        "version",
        "format",
        "thread",
        "part",
        "scheduled post",
        "Post now",
    ):
        assert term in instructions
    assert "every part" in instructions
    assert "explicit yes" in instructions
    assert "at most one scheduled post" in instructions
    assert "Only a draft or a failed post takes feedback" in instructions


async def test_the_instructions_and_scheduling_tools_copy_the_post_s_text(subscribed, mcp):
    instructions = (await mcp.initialize())["instructions"]
    tools = await mcp.list_tools()

    assert "Every scheduled post comes from its post's text" in instructions
    assert "version's text can become a scheduled post" not in instructions.lower()
    for name in ("schedule_post", "post_now"):
        assert "the post's text" in tools[name]["description"]
        assert "post_id" in tools[name]["inputSchema"]["required"]
        assert "version_id" not in tools[name]["inputSchema"]["properties"]
    assert "version_id" not in tools["edit_scheduled_post"]["inputSchema"]["properties"]


async def test_the_instructions_and_give_feedback_rewrite_the_post_s_text(subscribed, mcp):
    instructions = (await mcp.initialize())["instructions"]
    description = (await mcp.list_tools())["give_feedback"]["description"]

    assert "Feedback rewrites the post's text" in instructions
    assert "starting text" in instructions
    assert "latest version" not in instructions.lower()
    assert "the post's text" in description
    assert "latest version" not in description.lower()


async def test_no_instruction_or_tool_description_says_final(subscribed, mcp):
    instructions = (await mcp.initialize())["instructions"]
    tools = await mcp.list_tools()

    assert "Final" not in instructions
    assert [name for name, tool in tools.items() if "Final" in tool["description"]] == []


async def test_tools_list_shows_the_inspiration_author_tools_with_their_annotations(
    subscribed, mcp
):
    tools = await mcp.list_tools()

    assert tools["list_inspiration_authors"]["annotations"]["readOnlyHint"] is True
    assert tools["add_inspiration_author"]["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
    }
    assert tools["remove_inspiration_author"]["annotations"]["destructiveHint"] is True
    assert tools["add_inspiration_author"]["inputSchema"]["required"] == ["handle"]
    assert tools["list_inspiration_authors"]["description"]


async def test_a_request_without_a_token_is_401_with_a_bearer_challenge(new_browser):
    response = await McpClient(new_browser(), None).send("tools/list")

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer resource_metadata=")
    assert response.json() == {"detail": "Not authenticated"}


async def test_an_unknown_token_is_401(subscribed, new_browser, mcp_access_token):
    response = await McpClient(new_browser(), mcp_access_token + "x").send("tools/list")

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer resource_metadata=")
    assert 'error="invalid_token"' in response.headers["www-authenticate"]
    assert response.json() == {"detail": "Could not validate credentials"}


async def test_a_web_session_access_token_is_401(subscribed, new_browser, authed_client):
    session_token = authed_client.headers["Authorization"].removeprefix("Bearer ")

    response = await McpClient(new_browser(), session_token).send("tools/list")

    assert response.status_code == 401
    assert 'error="invalid_token"' in response.headers["www-authenticate"]


async def test_a_suspended_users_token_is_401_until_the_suspension_ends(
    subscribed, mcp, user, suspend_user, lift_suspension
):
    await suspend_user(user.email)

    response = await mcp.send("tools/list")

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer resource_metadata=")
    await lift_suspension(user.email)
    assert (await mcp.send("tools/list")).status_code == 200


async def test_the_endpoint_refuses_get(subscribed, mcp):
    response = await mcp.http.get(MCP, headers=mcp.headers())

    assert response.status_code == 405


async def test_a_call_records_when_the_connection_was_last_used_at_most_once_a_minute(
    fixed_clock, subscribed, mcp, authed_client
):
    async def last_used_at() -> Optional[datetime]:
        response = await authed_client.get(CONNECTIONS)
        assert response.status_code == 200, response.text
        [connected] = response.json()["data"]
        used = connected["last_used_at"]
        return datetime.fromisoformat(used) if used is not None else None

    assert await last_used_at() is None
    await mcp.call_tool("list_inspiration_authors")
    assert await last_used_at() == FIXED_NOW

    fixed_clock.advance(timedelta(seconds=59))
    await mcp.call_tool("list_inspiration_authors")
    assert await last_used_at() == FIXED_NOW

    fixed_clock.advance(timedelta(seconds=1))
    await mcp.call_tool("list_inspiration_authors")
    assert await last_used_at() == FIXED_NOW + timedelta(minutes=1)


# TODO(#316): remove with API key authentication at the MCP endpoint.
async def test_an_api_key_works_at_the_endpoint_until_it_is_revoked(
    subscribed, new_browser, authed_client
):
    created = await authed_client.post(API_KEYS, json={"name": "Claude Code"})
    assert created.status_code == 201, created.text
    client = McpClient(new_browser(), created.json()["secret"])
    assert (await client.send("tools/list")).status_code == 200

    [listed] = (await authed_client.get(API_KEYS)).json()["data"]
    assert (await authed_client.delete(f"{API_KEYS}/{listed['id']}")).status_code == 204
    response = await client.send("tools/list")

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer resource_metadata=")


async def test_a_user_whose_subscription_ended_gets_the_subscribe_link_from_every_tool(
    subscribed, mcp, db
):
    await db.execute(delete(Subscription))
    await db.commit()

    for name, arguments in [
        ("list_inspiration_authors", {}),
        ("add_inspiration_author", {"handle": "levelsio"}),
        ("remove_inspiration_author", {"handle": "levelsio"}),
        ("connect_x", {}),
        ("manage_subscription", {}),
    ]:
        result = await mcp.call_tool(name, **arguments)

        assert error_text(result) == (
            "This needs a subscription. Subscribe to continue. http://localhost:5173/subscribe"
        )
        assert result["structuredContent"] == {"subscribe_url": "http://localhost:5173/subscribe"}


async def test_every_user_uses_the_tools_on_an_instance_that_sells_no_plans(sells_no_plans, mcp):
    result = await mcp.call_tool("list_inspiration_authors")

    assert result["isError"] is False
    assert result["structuredContent"] == {"data": []}


async def test_a_tool_over_its_per_user_limit_answers_retry_later(subscribed, mcp):
    for _ in range(20):
        await mcp.call_tool("remove_inspiration_author", handle="levelsio")

    result = await mcp.call_tool("remove_inspiration_author", handle="levelsio")

    assert error_text(result).startswith("You've called remove_inspiration_author too often.")
    assert result["structuredContent"]["retry_at"].endswith("Z")
    assert (await mcp.call_tool("list_inspiration_authors"))["isError"] is False


async def test_read_only_tools_allow_60_calls_a_minute(subscribed, mcp):
    for _ in range(60):
        assert (await mcp.call_tool("list_inspiration_authors"))["isError"] is False

    result = await mcp.call_tool("list_inspiration_authors")

    assert "retry_at" in result["structuredContent"]


async def test_tool_calls_capture_no_product_events(subscribed, mcp, fake_x_reader, monkeypatch):
    capture, identify = MagicMock(), MagicMock()
    monkeypatch.setattr(posthog_client, "capture", capture)
    monkeypatch.setattr(posthog_client, "identify", identify)
    fake_x_reader.posts["levelsio"] = [FetchedPost(post_id="1", text="hi", posted_at=FIXED_NOW)]

    await mcp.initialize()
    await mcp.list_tools()
    await mcp.call_tool("add_inspiration_author", handle="levelsio")
    await mcp.call_tool("list_inspiration_authors")
    await mcp.call_tool("remove_inspiration_author", handle="levelsio")

    capture.assert_not_called()
    identify.assert_not_called()


async def test_an_unexpected_error_is_reported_and_answered_without_its_details(
    subscribed, mcp, fake_x_reader, fake_posthog, monkeypatch
):
    async def broken(handle: str):
        raise RuntimeError("secret internals")

    monkeypatch.setattr(fake_x_reader, "look_up_profile", broken)

    result = await mcp.call_tool("add_inspiration_author", handle="levelsio")

    assert error_text(result) == (
        "Something went wrong. Please try again later or contact us for support."
    )
    error_id = result["structuredContent"]["error_id"]
    fake_posthog.capture_exception.assert_called_once()
    properties = fake_posthog.capture_exception.call_args.kwargs["properties"]
    assert properties == {"error_id": error_id, "path": MCP, "method": "POST"}
