"""
The MCP server (ADR 0012): every area's tools behind API key authentication, the access gate
and per-User limits, served at one stateless Streamable HTTP endpoint that `main` mounts.
"""

import functools
import inspect
import logging
from contextlib import AsyncExitStack
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from fastapi import FastAPI, Request, status
from mcp.server.mcpserver import MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

import pumpkit.auth.mediator as auth_mediator
import pumpkit.auth.service.users as user_service
import pumpkit.authors.tools as authors_tools
import pumpkit.billing.service as billing_service
import pumpkit.billing.tools as billing_tools
import pumpkit.posts.tools as posts_tools
import pumpkit.scheduling.tools as scheduling_tools
from pumpkit.auth.dependencies import CREDENTIALS_INVALID
from pumpkit.billing.dependencies import SUBSCRIPTION_NEEDED
from pumpkit.core.config import settings
from pumpkit.core.db.session import get_async_db
from pumpkit.core.mcp_tools import McpTool, ToolCall, error_result, resolve, tool_error
from pumpkit.core.rate_limit import hit_user_limit
from pumpkit.core.time import get_clock

TOOLS: list[McpTool] = [
    *authors_tools.TOOLS,
    *posts_tools.TOOLS,
    *scheduling_tools.TOOLS,
    *billing_tools.TOOLS,
]

INSTRUCTIONS = """\
Pumpkit writes X posts in the style of X accounts the user picks, their inspiration authors \
(up to three), and publishes them on X.

- A brief says what a post is about and what the user thinks about it. Starting a post from \
a brief makes its first version.
- A post has one text, the text meant for X, with one text per part for a thread. It is what \
the user sees and edits by hand in the web app, and `get_post` says whether it was `edited` \
since the version it came from.
- Feedback rewrites the post's text as it is, the user's hand edits included, and makes the \
next version, which becomes the text. The writing sees every version in order, so feedback such \
as "like version 2, with a different hook" works. A version whose feedback was given on a text \
other than the version before keeps that text as its starting text.
- Each version has a format: a single X post, or a thread. A thread is several ordered parts, \
each one X post, published on X with each part replying to the one before. A \
post starts as a single X post unless the user asks for a thread, and feedback may switch the \
format.
- Every version stays in the post's history. `restore_version` makes an earlier one the \
post's text again, by its number, without writing a new version; feedback then rewrites it.
- The post's text can become a scheduled post, published at a chosen time or at once with Post \
now: `schedule_post` and `post_now` take the post. A scheduled post copied from a thread keeps \
every part, in order. Every scheduled post comes from its post's text: there is no typing one \
by hand.
- A post goes out once, so it has at most one scheduled post. To change one already \
scheduled, edit it, or delete it first, which makes the post a draft again. Only a draft or a \
failed post takes feedback: a scheduled or published one doesn't.
- Each post started and each feedback uses one generation of the user's allowance, \
and each X post published uses one X post, each part of a thread counting as one. Write a new \
version only when the user asks for one. `get_usage` says what is left and when it resets.
- Connecting X and subscribing happen in the Pumpkit web app. The tools for them answer with \
a link to open.
- Before Post now, show the user the exact text of every part that will be published, in \
order, and get their explicit yes. Post now publishes at once and can't be undone.
"""

# A Bearer key guards the endpoint, so a rebinding attack has nothing to reach; the default
# check would also refuse every Instance's own Host.
_TRANSPORT_SECURITY = TransportSecuritySettings(enable_dns_rebinding_protection=False)

# Each request starts and stops its own session manager, which would log both at INFO.
logging.getLogger("mcp.server.streamable_http_manager").setLevel(logging.WARNING)


@dataclass(frozen=True)
class _Caller:
    app: FastAPI
    request: Request
    user_id: str


# Set for the length of one authenticated request, read by each tool that request calls.
_caller: ContextVar[_Caller] = ContextVar("mcp_caller")


def _subscription_needed() -> CallToolResult:
    subscribe_url = settings.billing_page_url()
    return tool_error(f"{SUBSCRIPTION_NEEDED} {subscribe_url}", subscribe_url=subscribe_url)


def _handler(tool: McpTool) -> Callable[..., Awaitable[Any]]:
    """
    The function the SDK calls for `tool`: it counts the call against the User's limit, checks
    access, then runs the tool with a `ToolCall`, answering any refusal as a tool error.
    """
    run = tool.run
    name = run.__name__
    signature = inspect.signature(run, eval_str=True)

    @functools.wraps(run)
    async def handler(**arguments: Any) -> Any:
        caller = _caller.get()
        try:
            hit_user_limit(name, caller.user_id, tool.rate)
            # A refusal raised in here still reaches the session provider, which rolls back.
            async with AsyncExitStack() as stack:
                db = await resolve(caller.app, stack, get_async_db)
                clock = await resolve(caller.app, stack, get_clock)
                user = await user_service.get_user_by_id(db=db, user_id=caller.user_id)
                if user is None:
                    return tool_error(CREDENTIALS_INVALID)
                if not await billing_service.has_access(db, user_id=user.id):
                    return _subscription_needed()
                call = ToolCall(user=user, db=db, now=clock(), app=caller.app, stack=stack)
                return await run(call, **arguments)
        except Exception as exc:
            return error_result(exc, caller.request)

    # The SDK builds the input schema from this signature, so it must not show the ToolCall.
    handler.__signature__ = signature.replace(  # pyright: ignore[reportAttributeAccessIssue]
        parameters=list(signature.parameters.values())[1:]
    )
    return handler


def build_server(tools: list[McpTool]) -> MCPServer:
    server = MCPServer(name="pumpkit", instructions=INSTRUCTIONS)
    for tool in tools:
        server.add_tool(_handler(tool), annotations=tool.annotations)
    return server


class McpEndpoint:
    """
    The ASGI app at `/api/v1/mcp`. It answers 401 with a Bearer challenge unless an API key
    authenticates the request, then serves it with a session manager of its own: stateless
    requests share nothing, and FastAPI never runs a lifespan the manager could start in tests.
    """

    def __init__(self, server: MCPServer) -> None:
        self._server = server

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        app: FastAPI = scope["app"]
        secret = _bearer_secret(scope)
        if secret is None:
            await _unauthorized("Not authenticated")(scope, receive, send)
            return
        user_id = await _authenticate(app, secret)
        if user_id is None:
            await _unauthorized(CREDENTIALS_INVALID)(scope, receive, send)
            return

        token = _caller.set(_Caller(app=app, request=Request(scope), user_id=user_id))
        try:
            manager = StreamableHTTPSessionManager(
                app=self._server._lowlevel_server,
                stateless=True,
                json_response=True,
                security_settings=_TRANSPORT_SECURITY,
            )
            async with manager.run():
                await manager.handle_request(scope, receive, send)
        finally:
            _caller.reset(token)


def _bearer_secret(scope: Scope) -> Optional[str]:
    scheme, _, secret = Headers(scope=scope).get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not secret:
        return None
    return secret


async def _authenticate(app: FastAPI, secret: str) -> Optional[str]:
    """The id of the User the API key acts for, or None to refuse it."""
    async with AsyncExitStack() as stack:
        db = await resolve(app, stack, get_async_db)
        clock = await resolve(app, stack, get_clock)
        user = await auth_mediator.authenticate_api_key(db=db, secret=secret, now=clock())
        return user.id if user is not None else None


def _unauthorized(detail: str) -> JSONResponse:
    """The 401 `get_current_user` answers with, worded the same."""
    return JSONResponse(
        {"detail": detail},
        status_code=status.HTTP_401_UNAUTHORIZED,
        headers={"WWW-Authenticate": "Bearer"},
    )


endpoint = McpEndpoint(build_server(TOOLS))
