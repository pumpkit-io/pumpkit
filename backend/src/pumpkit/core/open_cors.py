"""CORS for the paths browser-based MCP clients call: any origin, never credentials."""

from starlette.datastructures import MutableHeaders
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_PREFIXES = ("/.well-known/oauth-", "/.well-known/openid-configuration")
_PATHS = frozenset(
    {"/api/v1/oauth/token", "/api/v1/oauth/register", "/api/v1/oauth/revoke", "/api/v1/mcp"}
)
_ALLOWED_HEADERS = (
    "Authorization, Content-Type, MCP-Protocol-Version, Mcp-Session-Id, Last-Event-ID"
)
_EXPOSED_HEADERS = "WWW-Authenticate, Mcp-Session-Id"


def _is_open(path: str) -> bool:
    return path in _PATHS or path.startswith(_PREFIXES)


class OpenCorsMiddleware:
    """
    Answers preflights and tags responses on the discovery, token, registration, revocation
    and MCP paths only. Safe because none of them reads cookies; the authorization endpoint
    and the consent and Settings APIs must stay out, and keep the app's strict policy.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not _is_open(scope["path"]):
            await self.app(scope, receive, send)
            return

        if scope["method"] == "OPTIONS":
            response = Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": _ALLOWED_HEADERS,
                    "Access-Control-Max-Age": "600",
                },
            )
            await response(scope, receive, send)
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                # Replaces what the strict middleware inside may have set for PUBLIC_URL.
                if "access-control-allow-credentials" in headers:
                    del headers["access-control-allow-credentials"]
                headers["Access-Control-Allow-Origin"] = "*"
                headers["Access-Control-Expose-Headers"] = _EXPOSED_HEADERS
            await send(message)

        await self.app(scope, receive, send_with_cors)
