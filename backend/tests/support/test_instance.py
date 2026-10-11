import pytest

from pumpkit.core.config import settings


@pytest.fixture
def posthog_off(monkeypatch):
    monkeypatch.setattr(settings, "POSTHOG_PROJECT_API_KEY", None)


@pytest.fixture
def google_off(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", None)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", None)


@pytest.fixture
def posthog_on(monkeypatch):
    monkeypatch.setattr(settings, "POSTHOG_PROJECT_API_KEY", "phc_test")
    monkeypatch.setattr(settings, "POSTHOG_HOST", "https://pumpkit.example/ph-relay")
    monkeypatch.setattr(settings, "POSTHOG_UI_HOST", "https://eu.posthog.com")


async def test_instance_without_posthog_has_no_analytics(
    client, posthog_off, no_operator_details, monkeypatch
):
    monkeypatch.setattr(settings, "APP_NAME", "acmeWriter")

    response = await client.get("/api/v1/instance")

    assert response.status_code == 200
    assert response.json() == {
        "app_name": "acmeWriter",
        "sells_plans": True,
        "sign_in_methods": ["magic_link", "google"],
        "operator": None,
        "analytics": None,
    }


async def test_instance_with_posthog_carries_its_settings(client, posthog_on):
    response = await client.get("/api/v1/instance")

    assert response.status_code == 200
    assert response.json()["analytics"] == {
        "key": "phc_test",
        "host": "https://pumpkit.example/ph-relay",
        "ui_host": "https://eu.posthog.com",
    }


async def test_instance_answers_without_a_session(new_browser, posthog_off):
    response = await new_browser().get("/api/v1/instance")

    assert response.status_code == 200
    assert response.json()["app_name"] == settings.APP_NAME


async def test_an_instance_without_stripe_sells_no_plans(client, sells_no_plans):
    response = await client.get("/api/v1/instance")

    assert response.json()["sells_plans"] is False


async def test_an_instance_with_stripe_sells_plans(client):
    response = await client.get("/api/v1/instance")

    assert response.json()["sells_plans"] is True


async def test_instance_without_google_offers_only_the_magic_link(client, google_off):
    response = await client.get("/api/v1/instance")

    assert response.json()["sign_in_methods"] == ["magic_link"]


async def test_instance_with_google_offers_both_sign_in_methods(client):
    response = await client.get("/api/v1/instance")

    assert response.json()["sign_in_methods"] == ["magic_link", "google"]


async def test_instance_without_operator_details_has_no_operator(client, no_operator_details):
    response = await client.get("/api/v1/instance")

    assert response.json()["operator"] is None


async def test_instance_with_operator_details_carries_them(client, monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_NAME", "Example S.R.L.")
    monkeypatch.setattr(settings, "OPERATOR_ADDRESS", "Via Roma 1, Milano, Italy")
    monkeypatch.setattr(settings, "SUPPORT_EMAIL", "help@example.org")
    monkeypatch.setattr(settings, "OPERATOR_VAT_ID", "IT01234567890")
    monkeypatch.setattr(settings, "OPERATOR_PEC", "example@pec.it")

    response = await client.get("/api/v1/instance")

    assert response.json()["operator"] == {
        "name": "Example S.R.L.",
        "address": "Via Roma 1, Milano, Italy",
        "vat_id": "IT01234567890",
        "rea": None,
        "share_capital": None,
        "pec": "example@pec.it",
        "support_email": "help@example.org",
    }
