from pumpkit.core.config import Settings


def test_settings_boot_without_optional_providers(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for key in (
        "POSTHOG_ENABLED",
        "POSTHOG_PROJECT_API_KEY",
        "POSTHOG_PERSONAL_API_KEY",
        "POSTHOG_HOST",
    ):
        monkeypatch.delenv(key, raising=False)
    s = Settings()  # pyright: ignore[reportCallIssue]
    assert s.OPENROUTER_API_KEY is None
    assert s.POSTHOG_ENABLED is False
    assert s.POSTHOG_PROJECT_API_KEY is None
    assert s.POSTHOG_HOST == "https://eu.i.posthog.com"


def test_an_empty_scheduled_posts_cap_means_no_cap(monkeypatch):
    monkeypatch.setenv("SCHEDULED_POSTS_MONTHLY_CAP", "")
    s = Settings()  # pyright: ignore[reportCallIssue]
    assert s.SCHEDULED_POSTS_MONTHLY_CAP is None


def test_an_unset_scheduled_posts_cap_defaults_to_100(monkeypatch):
    monkeypatch.delenv("SCHEDULED_POSTS_MONTHLY_CAP", raising=False)
    s = Settings()  # pyright: ignore[reportCallIssue]
    assert s.SCHEDULED_POSTS_MONTHLY_CAP == 100
