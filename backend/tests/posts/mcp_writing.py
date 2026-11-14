"""Writing a Post over MCP as an AI app does: `plan_posts`, then `write_posts`."""

from tests.mcp_client import McpClient


async def write_single_post(mcp: McpClient, brief: str) -> dict:
    """
    Plan `brief` and start writing its single-post Idea, which covers the whole Brief. The
    `write_posts` result, which a test reads for a refusal.
    """
    planned = await mcp.call_tool("plan_posts", brief=brief)
    assert planned["isError"] is False, planned
    plan = planned["structuredContent"]
    return await mcp.call_tool(
        "write_posts", brief_id=plan["brief_id"], idea_ids=[plan["single_post"]["id"]]
    )


async def single_post_id(mcp: McpClient, brief: str) -> str:
    """The id of the Post `write_single_post` started."""
    result = await write_single_post(mcp, brief)
    assert result["isError"] is False, result
    [post] = result["structuredContent"]["posts"]
    return post["id"]
