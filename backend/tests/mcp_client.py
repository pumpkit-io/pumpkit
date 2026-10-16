"""A JSON-RPC client for the MCP endpoint, as Claude Code talks to it over Streamable HTTP."""

from typing import Any, Optional

from httpx import AsyncClient, Response

MCP = "/api/v1/mcp"
PROTOCOL_VERSION = "2025-11-25"


class McpClient:
    """
    Sends one JSON-RPC request per POST, with the API key as a bearer header. The endpoint is
    stateless, so no `initialize` has to come first.
    """

    def __init__(self, http: AsyncClient, key: Optional[str]) -> None:
        self.http = http
        self.key = key

    def headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.key is not None:
            headers["Authorization"] = f"Bearer {self.key}"
        return headers

    async def send(self, method: str, params: Optional[dict[str, Any]] = None) -> Response:
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            message["params"] = params
        return await self.http.post(MCP, headers=self.headers(), json=message)

    async def result(self, method: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        response = await self.send(method, params)
        assert response.status_code == 200, response.text
        body = response.json()
        assert "result" in body, body
        return body["result"]

    async def initialize(self) -> dict[str, Any]:
        return await self.result(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "tests", "version": "0"},
            },
        )

    async def list_tools(self) -> dict[str, dict[str, Any]]:
        """The tools by name."""
        tools = (await self.result("tools/list"))["tools"]
        return {tool["name"]: tool for tool in tools}

    async def call_tool(self, name: str, **arguments: Any) -> dict[str, Any]:
        """The tool result: `content`, `isError` and, when there is one, `structuredContent`."""
        return await self.result("tools/call", {"name": name, "arguments": arguments})


def error_text(result: dict[str, Any]) -> str:
    """The text of a tool error, asserting the result is one."""
    assert result["isError"] is True, result
    return result["content"][0]["text"]
