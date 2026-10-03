import re
from typing import Mapping
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logger import logger
from app.core.posthog import posthog_client

_REDACTED = "[redacted]"
_SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "stripe-signature", "x-api-key"}
_SENSITIVE_QUERY_KEY = re.compile(r"token|code|state|password|secret", re.IGNORECASE)


def _redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {k: (_REDACTED if k.lower() in _SENSITIVE_HEADERS else v) for k, v in headers.items()}


def _redact_query(params: Mapping[str, str]) -> dict[str, str]:
    return {k: (_REDACTED if _SENSITIVE_QUERY_KEY.search(k) else v) for k, v in params.items()}


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:

    # 8-characters ID to identify the error. We may want the user to share
    # this ID with us for support, so it's better to have a short ID.
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
        exc_info=exc,  # Log full traceback
    )

    # Forward to PostHog Error Tracking. Tagging with the same error_id makes
    # support correlation possible: user shares the ID, we find the trace.
    posthog_client.capture_exception(
        exc,
        properties={
            "error_id": error_id,
            "path": request.url.path,
            "method": request.method,
        },
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Something went wrong. Please try again later or contact us for support.",
            "error_id": error_id,  # Share the error ID with the client - do not leak the error details
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire global exception handlers onto the FastAPI app."""
    app.add_exception_handler(Exception, unhandled_exception_handler)
