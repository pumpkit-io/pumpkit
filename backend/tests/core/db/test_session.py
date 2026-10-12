import pytest

from pumpkit.core.config import settings
from pumpkit.core.db.session import DatabaseSessionHandler


@pytest.mark.parametrize("env", ["local", "prod"])
def test_app_connects_with_ssl_when_postgres_ssl_is_require(monkeypatch, env):
    monkeypatch.setattr(settings, "ENV", env)
    monkeypatch.setattr(settings, "POSTGRES_SSL", "require")

    handler = DatabaseSessionHandler()

    assert handler.url.endswith("?sslmode=require")
    assert handler.async_url.endswith("?ssl=require")


@pytest.mark.parametrize("env", ["local", "prod"])
def test_app_connects_without_ssl_by_default(monkeypatch, env):
    monkeypatch.setattr(settings, "ENV", env)

    handler = DatabaseSessionHandler()

    assert "ssl" not in handler.url
    assert "ssl" not in handler.async_url
