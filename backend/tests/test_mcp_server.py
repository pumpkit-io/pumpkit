"""
The MCP endpoint: OAuth access token authentication (ADR 0020), the access gate and limits every
tool shares (ADR 0012).
"""

from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import MagicMock

from sqlalchemy import delete

from pumpkit.billing.models import Subscription
from pumpkit.core.analytics import posthog_client
from tests.conftest import FIXED_NOW
from tests.mcp_client import MCP, McpClient, error_text
from tests.positioning.positioning import TEXT as POSITIONING
from tests.posts.writing_replies import POST_IDEAS

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


async def test_the_instructions_say_pumpkit_chooses_a_thread_and_a_brief_can_ask_for_one(
    subscribed, mcp
):
    instructions = (await mcp.initialize())["instructions"]

    assert "Pumpkit chooses the format when it plans the post" in instructions
    assert "or when the brief asks for one" in instructions
    assert "A thread is written in the style" not in instructions
    assert "unless the user asks for a thread" not in instructions


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
    assert '`give_feedback` answers with `writing_state` "writing"' in instructions
    assert "starting text" in instructions
    assert "latest version" not in instructions.lower()
    assert "the post's text" in description
    assert "latest version" not in description.lower()


async def test_no_instruction_or_tool_description_says_final(subscribed, mcp):
    instructions = (await mcp.initialize())["instructions"]
    tools = await mcp.list_tools()

    assert "Final" not in instructions
    assert [name for name, tool in tools.items() if "Final" in tool["description"]] == []


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
    await mcp.call_tool("get_positioning")
    assert await last_used_at() == FIXED_NOW

    fixed_clock.advance(timedelta(seconds=59))
    await mcp.call_tool("get_positioning")
    assert await last_used_at() == FIXED_NOW

    fixed_clock.advance(timedelta(seconds=1))
    await mcp.call_tool("get_positioning")
    assert await last_used_at() == FIXED_NOW + timedelta(minutes=1)


async def test_an_api_key_is_401(subscribed, new_browser):
    api_key = "pumpkit_" + "k" * 43

    response = await McpClient(new_browser(), api_key).send("tools/list")

    assert response.status_code == 401
    assert 'error="invalid_token"' in response.headers["www-authenticate"]


async def test_the_api_key_routes_are_gone(subscribed, authed_client):
    assert (await authed_client.get(API_KEYS)).status_code == 404
    assert (await authed_client.post(API_KEYS, json={"name": "Claude Code"})).status_code == 404


async def test_a_user_whose_subscription_ended_gets_the_subscribe_link_from_gated_tools(
    subscribed, mcp, db
):
    await db.execute(delete(Subscription))
    await db.commit()

    for name, arguments in [
        ("get_positioning", {}),
        ("set_positioning", {"text": "I post about bootstrapping."}),
        ("manage_subscription", {}),
    ]:
        result = await mcp.call_tool(name, **arguments)

        assert error_text(result) == (
            "This needs a subscription. Subscribe to continue. http://localhost:5173/subscribe"
        )
        assert result["structuredContent"] == {"subscribe_url": "http://localhost:5173/subscribe"}


async def test_every_user_uses_the_tools_on_an_instance_that_sells_no_plans(sells_no_plans, mcp):
    result = await mcp.call_tool("get_positioning")

    assert result["isError"] is False
    assert result["structuredContent"] == {"text": None, "saved_at": None}


async def test_x_identity_can_get_its_reconnect_link_after_paid_access_ends(
    subscribed, mcp, db, user
):
    user.x_user_id = "1001"
    user.x_handle = "ada"
    await db.execute(delete(Subscription))
    await db.commit()

    result = await mcp.call_tool("connect_x")

    assert result["isError"] is False, result
    assert result["structuredContent"]["url"] == "http://localhost:5173/settings"
    assert "Reconnect the X account you signed in with" in result["structuredContent"]["message"]
    assert "disconnect" not in result["structuredContent"]["message"]
    assert (await mcp.call_tool("get_positioning"))["isError"] is True


async def test_a_tool_over_its_per_user_limit_answers_retry_later(subscribed, mcp):
    for _ in range(20):
        await mcp.call_tool("set_positioning", text=POSITIONING)

    result = await mcp.call_tool("set_positioning", text=POSITIONING)

    assert error_text(result).startswith("You've called set_positioning too often.")
    assert result["structuredContent"]["retry_at"].endswith("Z")
    assert (await mcp.call_tool("get_positioning"))["isError"] is False


async def test_read_only_tools_allow_60_calls_a_minute(subscribed, mcp):
    for _ in range(60):
        assert (await mcp.call_tool("get_positioning"))["isError"] is False

    result = await mcp.call_tool("get_positioning")

    assert "retry_at" in result["structuredContent"]


async def test_tool_calls_capture_no_product_events(subscribed, mcp, monkeypatch):
    capture, identify = MagicMock(), MagicMock()
    monkeypatch.setattr(posthog_client, "capture", capture)
    monkeypatch.setattr(posthog_client, "identify", identify)

    await mcp.initialize()
    await mcp.list_tools()
    await mcp.call_tool("set_positioning", text=POSITIONING)
    await mcp.call_tool("get_positioning")
    await mcp.call_tool("get_usage")

    capture.assert_not_called()
    identify.assert_not_called()


async def test_an_unexpected_error_is_reported_and_answered_without_its_details(
    subscribed, mcp, fake_llm, fake_posthog
):
    await mcp.call_tool("set_positioning", text=POSITIONING)
    fake_llm.standing[POST_IDEAS] = RuntimeError("secret internals")

    result = await mcp.call_tool("plan_posts", brief="ship small things")

    assert error_text(result) == (
        "Something went wrong. Please try again later or contact us for support."
    )
    error_id = result["structuredContent"]["error_id"]
    fake_posthog.capture_exception.assert_called_once()
    properties = fake_posthog.capture_exception.call_args.kwargs["properties"]
    assert properties == {"error_id": error_id, "path": MCP, "method": "POST"}
