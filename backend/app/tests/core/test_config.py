from app.core.config import Settings


def test_settings_boot_without_optional_providers(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for key in ("POSTHOG_ENABLED", "POSTHOG_PROJECT_API_KEY", "POSTHOG_PERSONAL_API_KEY", "POSTHOG_HOST"):
        monkeypatch.delenv(key, raising=False)
    s = Settings()
    assert s.OPENROUTER_API_KEY is None
    assert s.POSTHOG_ENABLED is False
    assert s.POSTHOG_PROJECT_API_KEY is None
    assert s.POSTHOG_HOST == "https://eu.i.posthog.com"
