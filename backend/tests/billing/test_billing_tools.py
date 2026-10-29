"""The billing MCP tool, which only links to the web app: subscribing needs a browser."""

from sqlalchemy import delete

from pumpkit.billing.models import Subscription

BILLING_PAGE = "http://localhost:5173/billing"


async def test_manage_subscription_links_to_settings_through_the_billing_route(subscribed, mcp):
    result = await mcp.call_tool("manage_subscription")

    assert result["isError"] is False, result
    assert result["structuredContent"]["url"] == BILLING_PAGE
    assert result["structuredContent"]["message"] == (
        f"Subscribe or manage your Subscription on the Settings page: {BILLING_PAGE}"
    )


async def test_a_user_whose_subscription_ended_gets_the_link_to_subscribe_again(
    subscribed, mcp, db
):
    await db.execute(delete(Subscription))
    await db.commit()

    result = await mcp.call_tool("manage_subscription")

    assert result["isError"] is False, result
    assert result["structuredContent"]["url"] == BILLING_PAGE


async def test_an_instance_that_sells_no_plans_says_so_instead_of_linking(sells_no_plans, mcp):
    result = await mcp.call_tool("manage_subscription")

    assert result["structuredContent"] == {
        "message": "This Instance sells no Plans: you can use all of Pumpkit without a "
        "Subscription.",
        "url": None,
    }


async def test_tools_list_shows_manage_subscription_as_read_only(subscribed, mcp):
    tools = await mcp.list_tools()

    assert tools["manage_subscription"]["annotations"]["readOnlyHint"] is True


async def test_manage_subscription_allows_60_calls_a_minute(subscribed, mcp):
    for _ in range(60):
        assert (await mcp.call_tool("manage_subscription"))["isError"] is False

    result = await mcp.call_tool("manage_subscription")

    assert "retry_at" in result["structuredContent"]
