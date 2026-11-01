"""The MCP endpoint authenticates an app's OAuth access token (ADR 0020)."""

from datetime import timedelta

import pytest
from sqlalchemy import delete

from pumpkit.billing.models import Subscription
from pumpkit.core.config import settings
from tests.connected_apps.conftest import REVOKE, approved_code, exchange
from tests.mcp_client import MCP, McpClient, error_text

INVALID_TOKEN = 'error="invalid_token"'


@pytest.fixture
def app(new_browser):
    return new_browser()


@pytest.fixture
async def tokens(subscribed, clock, authed_client, app, oauth_client) -> dict[str, str]:
    code = await approved_code(authed_client, app, oauth_client)
    return (await exchange(app, oauth_client, code)).json()


@pytest.fixture
def mcp_app(app, tokens) -> McpClient:
    return McpClient(app, tokens["access_token"])


def assert_refused(response) -> None:
    assert response.status_code == 401, response.text
    challenge = response.headers["www-authenticate"]
    assert challenge.startswith("Bearer resource_metadata=")
    assert INVALID_TOKEN in challenge


async def test_an_access_token_lists_the_tools_and_calls_one(mcp_app):
    assert "list_inspiration_authors" in await mcp_app.list_tools()

    result = await mcp_app.call_tool("list_inspiration_authors")

    assert result["isError"] is False
    assert result["structuredContent"] == {"data": []}


async def test_an_expired_access_token_is_refused(mcp_app, clock):
    clock.advance(timedelta(hours=1))

    assert_refused(await mcp_app.send("tools/list"))


async def test_a_disconnected_apps_access_token_is_refused(app, oauth_client, tokens, mcp_app):
    await app.post(REVOKE, data={"client_id": oauth_client, "token": tokens["refresh_token"]})

    assert_refused(await mcp_app.send("tools/list"))


async def test_a_token_for_another_resource_is_refused(mcp_app, monkeypatch):
    # The Instance moved: the token was issued for the MCP URL it served before.
    monkeypatch.setattr(settings, "PUBLIC_URL", "https://pumpkit.example.org")

    assert_refused(await mcp_app.send("tools/list"))


async def test_a_suspended_users_access_token_is_refused_until_the_suspension_ends(
    mcp_app, user, suspend_user, lift_suspension
):
    await suspend_user(user.email)

    assert_refused(await mcp_app.send("tools/list"))
    await lift_suspension(user.email)
    assert (await mcp_app.send("tools/list")).status_code == 200


async def test_a_web_session_access_token_is_refused(app, authed_client):
    session_token = authed_client.headers["Authorization"].removeprefix("Bearer ")

    assert_refused(await McpClient(app, session_token).send("tools/list"))


async def test_a_refresh_token_is_not_an_access_token(app, tokens):
    assert_refused(await McpClient(app, tokens["refresh_token"]).send("tools/list"))


async def test_a_user_whose_subscription_ended_gets_the_subscribe_link(mcp_app, db):
    await db.execute(delete(Subscription))
    await db.commit()

    result = await mcp_app.call_tool("list_inspiration_authors")

    assert error_text(result) == (
        "This needs a subscription. Subscribe to continue. http://localhost:5173/subscribe"
    )


async def test_an_authenticated_get_is_405_allowing_post(mcp_app):
    response = await mcp_app.http.get(MCP, headers=mcp_app.headers())

    assert response.status_code == 405
    assert response.headers["allow"] == "POST"


async def test_every_tool_says_it_needs_oauth_sign_in(mcp_app):
    for name, tool in (await mcp_app.list_tools()).items():
        assert tool["_meta"]["securitySchemes"] == [{"type": "oauth2", "scopes": ["pumpkit"]}], name
