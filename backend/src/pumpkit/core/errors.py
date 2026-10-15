import math
import re
from datetime import datetime, timezone
from typing import Any, ClassVar, Mapping, Optional
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from pumpkit.core.analytics import posthog_client
from pumpkit.core.logging import logger


class AppError(Exception):
    """
    An error a client gets as its own HTTP response, from the one handler the app registers.

    Subclasses set `status_code`, `public_detail` and `reported`, and override
    `response_body` or `response_headers` when the response carries more.
    """

    status_code: ClassVar[int] = 500
    # What the client reads as `detail`; None shows `str(error)`, so it must hold no secrets.
    public_detail: ClassVar[Optional[str]] = None
    # Log and capture the error in PostHog, and add the `error_id` a User reports to support.
    reported: ClassVar[bool] = False

    def response_body(self) -> dict[str, Any]:
        return {"detail": self.public_detail if self.public_detail is not None else str(self)}

    def response_headers(self) -> Optional[dict[str, str]]:
        return None


class RetryLaterError(AppError):
    """
    A request refused until `retry_at`. Answered as a 429 whose body carries `detail` and
    `retry_at`, with a `Retry-After` header in whole seconds.
    """

    status_code = 429

    def __init__(self, detail: str, *, retry_at: datetime, now: datetime) -> None:
        super().__init__(detail)
        self.detail = detail
        self.retry_at = retry_at
        # Rounded up, so a client that waits exactly this long is not refused again.
        self.retry_after_seconds = max(1, math.ceil((retry_at - now).total_seconds()))

    def response_body(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "retry_at": self.retry_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    def response_headers(self) -> dict[str, str]:
        return {"Retry-After": str(self.retry_after_seconds)}


class NotConfiguredError(AppError):
    """An operator's setup gap, not a bug: the message names the missing variable."""

    # Set here so they override the adapter error a subclass lists after this class.
    status_code = 503
    public_detail = None
    reported = False


# What a client reads for an unexpected exception, whose details never leave the server.
UNEXPECTED_ERROR_DETAIL = "Something went wrong. Please try again later or contact us for support."

_REDACTED = "[redacted]"
_SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "stripe-signature", "x-api-key"}
_SENSITIVE_QUERY_KEY = re.compile(r"token|code|state|password|secret", re.IGNORECASE)


def _redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {k: (_REDACTED if k.lower() in _SENSITIVE_HEADERS else v) for k, v in headers.items()}


def _redact_query(params: Mapping[str, str]) -> dict[str, str]:
    return {k: (_REDACTED if _SENSITIVE_QUERY_KEY.search(k) else v) for k, v in params.items()}


def report_unexpected_exception(request: Request, exc: Exception) -> str:
    """
    Log and capture an unexpected exception; return the error ID a User reports to support.

    Browser flows that must land on a page instead of a JSON 500 call this directly.
    """

    # Short, so a User can read it out to support.
    error_id = uuid4().hex[:8]

    logger.error(
        "Unhandled exception [%s]: %s %s",
        error_id,
        request.method,
        request.url.path,
        extra={
            "error_id": error_id,
            "method": request.method,
            "path": request.url.path,
            "client": request.client.host if request.client else None,
            "headers": _redact_headers(request.headers),
            "path_params": request.path_params,
            "query_params": _redact_query(request.query_params),
        },
        exc_info=exc,
    )

    # The shared error_id lets support find the trace from the ID a User reports.
    posthog_client.capture_exception(
        exc,
        properties={
            "error_id": error_id,
            "path": request.url.path,
            "method": request.method,
        },
    )

    return error_id


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    error_id = report_unexpected_exception(request, exc)
    return JSONResponse(
        status_code=500,
        content={
            "detail": UNEXPECTED_ERROR_DETAIL,
            "error_id": error_id,
        },
    )


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    content = exc.response_body()
    if exc.reported:
        content["error_id"] = report_unexpected_exception(request, exc)
    return JSONResponse(
        status_code=exc.status_code, content=content, headers=exc.response_headers()
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    # Starlette runs this one in ServerErrorMiddleware, which re-raises after responding.
    app.add_exception_handler(Exception, unhandled_exception_handler)
