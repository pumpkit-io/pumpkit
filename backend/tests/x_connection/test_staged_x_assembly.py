import pytest
from httpx import ASGITransport, AsyncClient

from pumpkit.core.config import settings
from pumpkit.core.db.session import get_async_db
from pumpkit.x_connection.x_publisher import get_x_publisher
from tests.staged_x_app import LocalPhotoFetcher, create_app


def test_staged_browser_assembly_refuses_production(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "prod")
    with pytest.raises(RuntimeError, match="local"):
        create_app()


def test_staged_browser_assembly_requires_the_local_provider(monkeypatch):
    monkeypatch.setattr(settings, "X_API_URL", None)
    with pytest.raises(RuntimeError, match="local"):
        create_app()


async def test_staged_browser_assembly_exposes_the_prepared_start_without_a_user(
    monkeypatch, db_session_maker, fake_x_publisher
):
    monkeypatch.setattr(settings, "X_API_URL", "http://emulate:4002")
    monkeypatch.setattr(settings, "X_AUTHORIZE_URL", "http://x.local/i/oauth2/authorize")
    staged = create_app()

    async def db():
        async with db_session_maker() as session:
            yield session

    staged.dependency_overrides[get_async_db] = db
    staged.dependency_overrides[get_x_publisher] = lambda: fake_x_publisher
    async with AsyncClient(transport=ASGITransport(app=staged), base_url="http://test") as browser:
        assert (await browser.get("/")).status_code == 200
        assert (await browser.get("/api/v1/login/x")).status_code == 200


async def test_staged_photo_adapter_refuses_external_urls(monkeypatch):
    monkeypatch.setattr(settings, "X_API_URL", "http://emulate:4002")
    assert await LocalPhotoFetcher().fetch("https://example.com/avatar.png") is None
