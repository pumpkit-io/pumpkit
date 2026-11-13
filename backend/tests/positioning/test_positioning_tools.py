"""The Positioning MCP tools, refusing what the web routes refuse."""

from tests.mcp_client import error_text
from tests.positioning.positioning import POSITIONING, TEXT


async def test_get_positioning_answers_with_nothing_until_one_is_saved(subscribed, mcp):
    result = await mcp.call_tool("get_positioning")

    assert result["isError"] is False
    assert result["structuredContent"] == {"text": None, "saved_at": None}


async def test_set_positioning_saves_what_the_web_app_then_reads(
    subscribed, mcp, authed_client, fixed_clock
):
    result = await mcp.call_tool("set_positioning", text=f"  {TEXT}\n")

    assert result["isError"] is False
    assert result["structuredContent"] == {"text": TEXT, "saved_at": "2026-10-10T12:00:30Z"}
    assert (await mcp.call_tool("get_positioning"))["structuredContent"] == (
        result["structuredContent"]
    )
    assert (await authed_client.get(POSITIONING)).json() == result["structuredContent"]


async def test_a_blank_positioning_is_refused_in_words(subscribed, mcp):
    await mcp.call_tool("set_positioning", text=TEXT)

    result = await mcp.call_tool("set_positioning", text="   ")

    assert error_text(result) == "Write your positioning first."
    assert (await mcp.call_tool("get_positioning"))["structuredContent"]["text"] == TEXT


async def test_a_positioning_over_4000_characters_is_refused_in_words(subscribed, mcp):
    result = await mcp.call_tool("set_positioning", text="a" * 4001)

    assert error_text(result) == "A positioning can be up to 4,000 characters."


async def test_tools_list_shows_the_positioning_tools_with_their_annotations(subscribed, mcp):
    tools = await mcp.list_tools()

    assert tools["get_positioning"]["annotations"]["readOnlyHint"] is True
    assert tools["set_positioning"]["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
    }
    assert tools["set_positioning"]["inputSchema"]["required"] == ["text"]
    for name in ("get_positioning", "set_positioning"):
        assert "who they write for" in tools[name]["description"]
