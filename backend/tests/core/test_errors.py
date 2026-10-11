import logging
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient, Response

import pumpkit.core.errors as errors_module
from pumpkit.authors.x_reader import HandleNotFoundError, XReaderError, XReaderNotConfiguredError
from pumpkit.billing.gateway import BillingProviderError
from pumpkit.core.errors import AppError, RetryLaterError
from pumpkit.core.llm import LLMError
from pumpkit.core.openrouter import LLMNotConfiguredError
from pumpkit.main import app as main_app
from pumpkit.x_connection.x_publisher import (
    XNotReceivedError,
    XOutcomeUnknownError,
    XPostRejectedError,
    XPublisherError,
    XPublisherNotConfiguredError,
    XRateLimitedError,
    XReconnectNeededError,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
ERROR_ID = re.compile(rb'"error_id":"([0-9a-f]{8})"')

BILLING_502 = (
    b'{"detail":"Billing is unavailable right now. Please try again later.","error_id":"%s"}'
)
LLM_502 = b'{"detail":"Writing the Post failed. Please try again.","error_id":"%s"}'
X_READER_502 = b'{"detail":"X can\'t be read right now. Please try again later.","error_id":"%s"}'
X_PUBLISHER_502 = (
    b'{"detail":"X isn\'t answering right now. Please try again later.","error_id":"%s"}'
)
UNHANDLED_500 = (
    b'{"detail":"Something went wrong. Please try again later or contact us for support.",'
    b'"error_id":"%s"}'
)

# The error a route raises, then the status and exact body a client gets.
# A body with an error_id is captured in PostHog; one without is not.
RESPONSES = [
    (BillingProviderError("stripe said sk_live_secret is wrong"), 502, BILLING_502),
    (LLMError("provider said no"), 502, LLM_502),
    (
        LLMNotConfiguredError(
            "OPENROUTER_API_KEY is not set. Add it to backend/.env to enable LLM calls."
        ),
        503,
        b'{"detail":"OPENROUTER_API_KEY is not set. Add it to backend/.env to enable LLM calls."}',
    ),
    (XReaderError("timeout"), 502, X_READER_502),
    (HandleNotFoundError("nobody"), 502, X_READER_502),
    (
        XReaderNotConfiguredError(),
        503,
        b'{"detail":"TWITTERAPI_IO_API_KEY is not set. Add it to backend/.env to read X posts."}',
    ),
    (XPublisherError("timeout"), 502, X_PUBLISHER_502),
    (XReconnectNeededError("revoked"), 502, X_PUBLISHER_502),
    (XRateLimitedError("429"), 502, X_PUBLISHER_502),
    (XNotReceivedError("dns"), 502, X_PUBLISHER_502),
    (XOutcomeUnknownError("504"), 502, X_PUBLISHER_502),
    (XPostRejectedError(403, "duplicate"), 502, X_PUBLISHER_502),
    (
        XPublisherNotConfiguredError(),
        503,
        b'{"detail":"X_CLIENT_ID, X_CLIENT_SECRET and X_REDIRECT_URI must be set in '
        b'backend/.env to connect X accounts."}',
    ),
    (RuntimeError("kaboom"), 500, UNHANDLED_500),
]


@pytest.fixture
def raise_from_main_app(monkeypatch):
    """Request the real app on a route that raises `error`."""

    async def _raise(error: Exception) -> Response:
        async def _route():
            raise error

        route = APIRoute("/raise-for-test", _route)
        monkeypatch.setattr(main_app.router, "routes", [*main_app.router.routes, route])
        transport = ASGITransport(app=main_app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/raise-for-test")

    return _raise


@pytest.mark.parametrize(
    ("error", "status_code", "body"),
    RESPONSES,
    ids=[type(error).__name__ for error, _, _ in RESPONSES],
)
async def test_main_app_answers_each_error_with_its_status_and_body(
    raise_from_main_app, fake_posthog, error, status_code, body
):
    response = await raise_from_main_app(error)

    assert response.status_code == status_code
    assert "retry-after" not in response.headers
    if b"error_id" in body:
        match = ERROR_ID.search(response.content)
        assert match
        assert response.content == body % match.group(1)
        fake_posthog.capture_exception.assert_called_once()
        properties = fake_posthog.capture_exception.call_args.kwargs["properties"]
        assert properties["error_id"] == match.group(1).decode()
    else:
        assert response.content == body
        fake_posthog.capture_exception.assert_not_called()


async def test_main_app_answers_retry_later_with_429_and_retry_after(
    raise_from_main_app, fake_posthog
):
    error = RetryLaterError(
        "Too many Versions. Try again later.",
        retry_at=NOW + timedelta(seconds=90, milliseconds=200),
        now=NOW,
    )

    response = await raise_from_main_app(error)

    assert response.status_code == 429
    assert response.content == (
        b'{"detail":"Too many Versions. Try again later.","retry_at":"2026-01-01T12:01:30.200000Z"}'
    )
    assert response.headers["retry-after"] == "91"
    fake_posthog.capture_exception.assert_not_called()


class _ClosedForMaintenanceError(AppError):
    status_code = 503
    public_detail = "Closed for maintenance."
    reported = True

    def response_headers(self) -> dict[str, str]:
        return {"Retry-After": "600"}


async def test_a_new_app_error_is_answered_without_registering_a_handler(
    raise_from_main_app, fake_posthog
):
    response = await raise_from_main_app(_ClosedForMaintenanceError("db migration running"))

    assert response.status_code == 503
    match = ERROR_ID.search(response.content)
    assert match
    assert response.content == b'{"detail":"Closed for maintenance.","error_id":"%s"}' % (
        match.group(1)
    )
    assert response.headers["retry-after"] == "600"
    fake_posthog.capture_exception.assert_called_once()


async def test_billing_provider_error_returns_502_with_error_id(monkeypatch):
    fake_posthog = MagicMock()
    monkeypatch.setattr(errors_module, "posthog_client", fake_posthog)

    test_app = FastAPI()
    errors_module.register_exception_handlers(test_app)

    @test_app.get("/billing")
    async def billing():
        raise BillingProviderError("stripe said sk_live_secret is wrong")

    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/billing")

    assert response.status_code == 502
    body = response.json()
    assert re.fullmatch(r"[0-9a-f]{8}", body["error_id"])
    assert "sk_live_secret" not in response.text
    _, kwargs = fake_posthog.capture_exception.call_args
    assert kwargs["properties"]["error_id"] == body["error_id"]


async def test_unhandled_exception_returns_500_with_error_id(monkeypatch):
    fake_posthog = MagicMock()
    monkeypatch.setattr(errors_module, "posthog_client", fake_posthog)

    test_app = FastAPI()
    errors_module.register_exception_handlers(test_app)

    @test_app.get("/boom")
    async def boom():
        raise RuntimeError("kaboom")

    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert re.fullmatch(r"[0-9a-f]{8}", body["error_id"])
    assert "kaboom" not in response.text
    fake_posthog.capture_exception.assert_called_once()
    _, kwargs = fake_posthog.capture_exception.call_args
    assert kwargs["properties"]["error_id"] == body["error_id"]
    assert kwargs["properties"]["path"] == "/boom"


async def test_exception_log_redacts_credentials(monkeypatch, caplog):
    monkeypatch.setattr(errors_module, "posthog_client", MagicMock())

    test_app = FastAPI()
    errors_module.register_exception_handlers(test_app)

    @test_app.get("/boom")
    async def boom():
        raise RuntimeError("kaboom")

    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    with caplog.at_level(logging.ERROR):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/boom",
                params={"token": "supersecret", "page": "2"},
                headers={"Authorization": "Bearer secret123", "Cookie": "refresh_token=abc"},
            )

    assert response.status_code == 500
    records = [r for r in caplog.records if r.levelno == logging.ERROR and hasattr(r, "error_id")]
    assert records
    for record in records:
        blob = record.getMessage() + repr(record.__dict__)
        for secret in ("secret123", "refresh_token=abc", "supersecret"):
            assert secret not in blob
        assert "/boom" in record.getMessage()
        assert record.headers["authorization"] == "[redacted]"
        assert record.headers["cookie"] == "[redacted]"
        assert record.query_params["token"] == "[redacted]"
        assert record.query_params["page"] == "2"
