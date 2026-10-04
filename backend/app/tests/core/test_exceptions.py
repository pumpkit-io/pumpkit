import logging
import re
from unittest.mock import MagicMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.core.exceptions as exceptions_module
from app.core.billing_gateway import BillingProviderError
from app.main import app as main_app


def test_main_app_registers_unhandled_exception_handler():
    assert (
        main_app.exception_handlers.get(Exception) is exceptions_module.unhandled_exception_handler
    )


def test_main_app_registers_billing_provider_error_handler():
    assert (
        main_app.exception_handlers.get(BillingProviderError)
        is exceptions_module.billing_provider_error_handler
    )


async def test_billing_provider_error_returns_502_with_error_id(monkeypatch):
    fake_posthog = MagicMock()
    monkeypatch.setattr(exceptions_module, "posthog_client", fake_posthog)

    test_app = FastAPI()
    exceptions_module.register_exception_handlers(test_app)

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
    monkeypatch.setattr(exceptions_module, "posthog_client", fake_posthog)

    test_app = FastAPI()
    exceptions_module.register_exception_handlers(test_app)

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
    monkeypatch.setattr(exceptions_module, "posthog_client", MagicMock())

    test_app = FastAPI()
    exceptions_module.register_exception_handlers(test_app)

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
