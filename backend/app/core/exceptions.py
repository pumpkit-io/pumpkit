import re
from datetime import timezone
from typing import Mapping
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.billing_gateway import BillingProviderError
from app.core.llm import LLMError
from app.core.logger import logger
from app.core.openrouter import LLMNotConfiguredError
from app.core.posthog import posthog_client
from app.core.retry_later import RetryLaterError
from app.core.x_reader import XReaderError, XReaderNotConfiguredError

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
            "detail": "Something went wrong. Please try again later or contact us for support.",
            "error_id": error_id,  # Never leak the error details to the client.
        },
    )


async def billing_provider_error_handler(request: Request, exc: Exception) -> JSONResponse:
    error_id = report_unexpected_exception(request, exc)
    return JSONResponse(
        status_code=502,
        content={
            "detail": "Billing is unavailable right now. Please try again later.",
            "error_id": error_id,
        },
    )


async def x_reader_error_handler(request: Request, exc: Exception) -> JSONResponse:
    error_id = report_unexpected_exception(request, exc)
    return JSONResponse(
        status_code=502,
        content={
            "detail": "X can't be read right now. Please try again later.",
            "error_id": error_id,
        },
    )


async def retry_later_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RetryLaterError)
    return JSONResponse(
        status_code=429,
        content={
            "detail": exc.detail,
            "retry_at": exc.retry_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


async def not_configured_handler(request: Request, exc: Exception) -> JSONResponse:
    # An operator's setup gap, not a bug: the message names the missing variable.
    return JSONResponse(status_code=503, content={"detail": str(exc)})


async def llm_error_handler(request: Request, exc: Exception) -> JSONResponse:
    error_id = report_unexpected_exception(request, exc)
    return JSONResponse(
        status_code=502,
        content={"detail": "Writing the Post failed. Please try again.", "error_id": error_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(BillingProviderError, billing_provider_error_handler)
    app.add_exception_handler(LLMError, llm_error_handler)
    app.add_exception_handler(LLMNotConfiguredError, not_configured_handler)
    app.add_exception_handler(RetryLaterError, retry_later_handler)
    app.add_exception_handler(XReaderNotConfiguredError, not_configured_handler)
    app.add_exception_handler(XReaderError, x_reader_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
