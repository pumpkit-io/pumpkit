"""
What every area's MCP tools module shares (ADR 0012): how a tool is declared, what it gets
about its call, and how the errors mediators raise become tool errors.
"""

import inspect
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Awaitable, Callable, Generic, TypeVar, overload

from fastapi import FastAPI, Request
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.core.errors import UNEXPECTED_ERROR_DETAIL, AppError, report_unexpected_exception

READ_ONLY = ToolAnnotations(read_only_hint=True)
# Clients treat a tool without annotations as destructive; this one adds or edits, never deletes.
ADDITIVE = ToolAnnotations(read_only_hint=False, destructive_hint=False)
# Clients ask the User before calling a destructive tool.
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True)

# The per-User limit of every read-only and browser-only tool.
READ_ONLY_RATE = "60/minute"

UserT = TypeVar("UserT")
T = TypeVar("T")


@dataclass(frozen=True)
class McpTool:
    """
    One tool, as an area's tools module declares it. `run` takes a `ToolCall` and then the
    tool's arguments, which become its input schema; its name and docstring are the tool's.
    """

    run: Callable[..., Awaitable[Any]]
    # Per User, in slowapi's notation; the web route's rate where the route has one.
    rate: str
    annotations: ToolAnnotations
    # Browser-only tools only answer with a link, so they skip the access gate.
    needs_access: bool = True


@dataclass(frozen=True)
class ToolCall(Generic[UserT]):
    """
    What a tool gets about its call: the User its API key acts for, the call's database session
    and the time, read once like a route's `clock()`.
    """

    user: UserT
    db: AsyncSession
    now: datetime
    app: FastAPI = field(repr=False)
    stack: AsyncExitStack = field(repr=False)

    async def provide(self, provider: Callable[[], T]) -> T:
        """A provider such as `get_x_reader`, or the app's override of it, as `Depends` gives it."""
        return await resolve(self.app, self.stack, provider)


@overload
async def resolve(
    app: FastAPI, stack: AsyncExitStack, provider: Callable[[], AsyncIterator[T]]
) -> T: ...
@overload
async def resolve(app: FastAPI, stack: AsyncExitStack, provider: Callable[[], T]) -> T: ...
async def resolve(app: FastAPI, stack: AsyncExitStack, provider: Callable[[], Any]) -> Any:
    """
    A zero-argument FastAPI provider, or the app's override of it, so tests' fakes apply.
    A generator provider is entered on `stack`, which closes it as the route's request would.
    """
    fn = app.dependency_overrides.get(provider, provider)
    if inspect.isasyncgenfunction(fn):
        return await stack.enter_async_context(asynccontextmanager(fn)())
    if inspect.isgeneratorfunction(fn):
        return stack.enter_context(contextmanager(fn)())
    result = fn()
    if inspect.isawaitable(result):
        result = await result
    return result


def tool_error(detail: str, **structured: Any) -> CallToolResult:
    """
    A tool error whose text is `detail` as is. Returned, not raised: the SDK prefixes the text
    of a raised error and hides everything else.
    """
    return CallToolResult(
        content=[TextContent(type="text", text=detail)],
        structured_content=structured or None,
        is_error=True,
    )


def error_result(exc: Exception, request: Request) -> CallToolResult:
    """
    The tool error for an exception a tool raised, with the web route's `detail`, then its fix
    page's `url` when it has one, and the rest of its body (`retry_at`, `error_id`). Reported
    errors go to PostHog as the handlers send them.
    """
    if isinstance(exc, ValidationError):
        return tool_error(_validation_detail(exc))
    if isinstance(exc, AppError):
        body = exc.response_body()
        if exc.reported:
            body["error_id"] = report_unexpected_exception(request, exc)
        detail = body.pop("detail")
        if "url" in body:
            detail = f"{detail} {body['url']}"
        return tool_error(detail, **body)
    return tool_error(UNEXPECTED_ERROR_DETAIL, error_id=report_unexpected_exception(request, exc))


def _validation_detail(exc: ValidationError) -> str:
    """The messages of a request schema's checks, without pydantic's "Value error, " prefix."""
    messages = []
    for error in exc.errors():
        cause = error.get("ctx", {}).get("error")
        messages.append(str(cause) if error["type"] == "value_error" and cause else error["msg"])
    return " ".join(messages)
