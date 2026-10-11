import pytest
from pydantic import ValidationError

from pumpkit.core.config import Settings

# What a Self-hoster must set: everything else has a default or belongs to an optional provider.
_INSTANCE_ENV = {
    "ENV": "local",
    "BACKEND_URL": "https://api.example.org",
    "BACKEND_PORT": "8000",
    "FRONTEND_URL": "https://app.example.org",
    "FRONTEND_PORT": "5173",
    "CORS_ORIGINS": '["https://app.example.org"]',
    "POSTGRES_USER": "postgres",
    "POSTGRES_PASSWORD": "postgres",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "postgres",
    "JWT_SECRET_KEY": "test-secret-key-test-secret-key-0123456789",
    "FERNET_ENCRYPTION_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    "RESEND_API_KEY": "re_test",
    "RESEND_NOREPLY_ADDRESS": "noreply@example.org",
    "RESEND_SUPPORT_ADDRESS": "support@example.org",
}

_STRIPE_ENV = {
    "STRIPE_SECRET_KEY": "sk_test_dummy",
    "STRIPE_PUBLISHABLE_KEY": "pk_test_dummy",
    "STRIPE_WEBHOOK_SECRET": "whsec_dummy",
    "BILLING_PLAN_KEYS": '["pumpkit_pro_monthly"]',
}

_GOOGLE_ENV = {
    "GOOGLE_CLIENT_ID": "client-id",
    "GOOGLE_CLIENT_SECRET": "client-secret",
}


@pytest.fixture
def instance_env(monkeypatch: pytest.MonkeyPatch):
    """Clears the suite's environment down to the settings that describe an Instance."""
    for key in Settings.model_fields:
        monkeypatch.delenv(key, raising=False)
    for key, value in _INSTANCE_ENV.items():
        monkeypatch.setenv(key, value)

    def build(**extra: str) -> Settings:
        for key, value in extra.items():
            monkeypatch.setenv(key, value)
        return Settings()  # pyright: ignore[reportCallIssue]

    return build


def test_internal_tunables_default_to_todays_values(instance_env):
    s = instance_env()

    assert s.APP_NAME == "Pumpkit"
    assert s.LOG_LEVEL == "INFO"
    assert s.JWT_ALGORITHM == "HS256"
    assert s.JWT_ACCESS_TOKEN_EXPIRE_MINUTES == 30
    assert s.JWT_REFRESH_TOKEN_EXPIRE_DAYS == 30
    assert s.JWT_ISSUER == "pumpkit"
    assert s.JWT_AUDIENCE == "pumpkit-api"
    assert s.COOKIE_MAX_AGE_SECONDS == 2592000
    assert s.MAGIC_LINK_TOKEN_DURATION_MINUTES == 15
    assert s.MAGIC_LINK_TOKEN_NUM_BYTES == 32
    assert s.GOOGLE_NONCE_TOKEN_NUM_BYTES == 64
    assert s.GOOGLE_CODE_VERIFIER_TOKEN_NUM_BYTES == 64
    assert s.GOOGLE_COOKIE_MAX_AGE_SECONDS == 600
    assert s.GOOGLE_TOKEN_ENDPOINT_TIMEOUT_SECONDS == 30
    assert s.BILLING_TRIAL_PERIOD_DAYS == 14


def test_return_urls_default_under_the_instance_urls(instance_env):
    s = instance_env()

    assert s.STRIPE_CHECKOUT_SUCCESS_URL == "https://app.example.org/billing/success"
    assert s.STRIPE_CHECKOUT_CANCEL_URL == "https://app.example.org/billing/cancelled"
    assert s.STRIPE_BILLING_PORTAL_RETURN_URL == "https://app.example.org/billing"
    assert s.GOOGLE_OAUTH_REDIRECT_URI == "https://api.example.org/api/v1/oauth/google/callback"


def test_explicit_return_urls_win_over_the_defaults(instance_env):
    s = instance_env(
        STRIPE_CHECKOUT_SUCCESS_URL="https://other.example.org/ok",
        GOOGLE_OAUTH_REDIRECT_URI="https://other.example.org/google",
    )

    assert s.STRIPE_CHECKOUT_SUCCESS_URL == "https://other.example.org/ok"
    assert s.GOOGLE_OAUTH_REDIRECT_URI == "https://other.example.org/google"


def test_providers_are_off_when_none_of_their_settings_are_set(instance_env):
    s = instance_env()

    assert s.is_stripe_billing_configured() is False
    assert s.is_google_configured() is False
    assert s.is_posthog_configured() is False


def test_providers_are_on_when_all_their_settings_are_set(instance_env):
    s = instance_env(**_STRIPE_ENV, **_GOOGLE_ENV, POSTHOG_PROJECT_API_KEY="phc_test")

    assert s.is_stripe_billing_configured() is True
    assert s.is_google_configured() is True
    assert s.is_posthog_configured() is True


@pytest.mark.parametrize(
    ("group", "unset"),
    [
        (_STRIPE_ENV, ["STRIPE_WEBHOOK_SECRET"]),
        (_STRIPE_ENV, ["STRIPE_PUBLISHABLE_KEY", "BILLING_PLAN_KEYS"]),
        (_STRIPE_ENV, ["STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET"]),
        (_GOOGLE_ENV, ["GOOGLE_CLIENT_SECRET"]),
        (_GOOGLE_ENV, ["GOOGLE_CLIENT_ID"]),
    ],
)
def test_partly_configured_provider_fails_naming_each_missing_setting(instance_env, group, unset):
    partial = {key: value for key, value in group.items() if key not in unset}

    with pytest.raises(ValidationError) as excinfo:
        instance_env(**partial)

    message = str(excinfo.value)
    for key in unset:
        assert key in message


def test_empty_plan_keys_count_as_unset(instance_env):
    stripe_without_plans = {**_STRIPE_ENV, "BILLING_PLAN_KEYS": "[]"}

    with pytest.raises(ValidationError, match="BILLING_PLAN_KEYS"):
        instance_env(**stripe_without_plans)


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
