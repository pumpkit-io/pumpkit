import pytest
from pydantic import ValidationError

from pumpkit.core.config import Settings

# What a Self-hoster must set: everything else has a default or belongs to an optional provider.
_INSTANCE_ENV = {
    "PUBLIC_URL": "https://pumpkit.example.org",
    "POSTGRES_PASSWORD": "postgres",
    "JWT_SECRET_KEY": "test-secret-key-test-secret-key-0123456789",
    "FERNET_ENCRYPTION_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
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

_SMTP_ENV = {
    "SMTP_HOST": "smtp.example.org",
    "EMAIL_FROM": "noreply@example.org",
}

_OPERATOR_ENV = {
    "OPERATOR_NAME": "Example S.R.L.",
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
    assert s.BILLING_TRIAL_PERIOD_DAYS == 7


def test_postgres_connection_defaults_to_the_bundled_database(instance_env):
    s = instance_env()

    assert (s.POSTGRES_USER, s.POSTGRES_HOST, s.POSTGRES_PORT, s.POSTGRES_DB) == (
        "postgres",
        "db",
        "5432",
        "postgres",
    )


def test_an_instance_runs_in_production_unless_told_otherwise(instance_env):
    assert instance_env().ENV == "prod"


def test_env_is_either_prod_or_local(instance_env):
    assert instance_env(ENV="local").ENV == "local"
    with pytest.raises(ValidationError, match="ENV"):
        instance_env(ENV="stg")


def test_a_domain_public_url_gives_every_url_the_instance_needs(instance_env):
    s = instance_env(PUBLIC_URL="https://pumpkit.example.org")

    assert s.frontend_url() == "https://pumpkit.example.org"
    assert s.api_url() == "https://pumpkit.example.org/api/v1"
    assert s.cors_origins() == ["https://pumpkit.example.org"]
    assert s.google_oauth_redirect_uri() == (
        "https://pumpkit.example.org/api/v1/oauth/google/callback"
    )
    assert s.x_redirect_uri() == "https://pumpkit.example.org/oauth/x/callback"
    assert s.stripe_checkout_success_url() == "https://pumpkit.example.org/billing/success"
    assert s.stripe_checkout_cancel_url() == "https://pumpkit.example.org/billing/cancelled"
    assert s.stripe_billing_portal_return_url() == "https://pumpkit.example.org/billing"


def test_a_localhost_public_url_keeps_its_port(instance_env):
    s = instance_env(PUBLIC_URL="http://localhost:8080")

    assert s.frontend_url() == "http://localhost:8080"
    assert s.api_url() == "http://localhost:8080/api/v1"
    assert s.cors_origins() == ["http://localhost:8080"]
    assert s.google_oauth_redirect_uri() == "http://localhost:8080/api/v1/oauth/google/callback"
    assert s.x_redirect_uri() == "http://localhost:8080/oauth/x/callback"
    assert s.stripe_checkout_success_url() == "http://localhost:8080/billing/success"
    assert s.stripe_checkout_cancel_url() == "http://localhost:8080/billing/cancelled"
    assert s.stripe_billing_portal_return_url() == "http://localhost:8080/billing"


def test_a_trailing_slash_on_the_public_url_is_dropped(instance_env):
    s = instance_env(PUBLIC_URL="https://pumpkit.example.org/")

    assert s.api_url() == "https://pumpkit.example.org/api/v1"
    assert s.cors_origins() == ["https://pumpkit.example.org"]


@pytest.mark.parametrize(
    "public_url",
    ["pumpkit.example.org", "ftp://pumpkit.example.org", "https://pumpkit.example.org/app"],
)
def test_a_public_url_that_is_not_a_bare_http_origin_fails_naming_it(instance_env, public_url):
    with pytest.raises(ValidationError, match="PUBLIC_URL"):
        instance_env(PUBLIC_URL=public_url)


def test_an_instance_needs_its_public_url(instance_env, monkeypatch):
    monkeypatch.delenv("PUBLIC_URL")

    with pytest.raises(ValidationError, match="PUBLIC_URL"):
        instance_env()


def test_providers_are_off_when_none_of_their_settings_are_set(instance_env):
    s = instance_env()

    assert s.is_stripe_billing_configured() is False
    assert s.is_google_configured() is False
    assert s.is_posthog_configured() is False
    assert s.is_smtp_configured() is False
    assert s.is_operator_configured() is False


def test_providers_are_off_when_their_settings_are_left_empty(instance_env):
    empty = {
        key: ""
        for key in (
            *_STRIPE_ENV,
            *_GOOGLE_ENV,
            *_SMTP_ENV,
            *_OPERATOR_ENV,
            "SUPPORT_EMAIL",
            "POSTHOG_PROJECT_API_KEY",
            "SMTP_PORT",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
        )
    }

    s = instance_env(**empty)

    assert s.is_stripe_billing_configured() is False
    assert s.is_google_configured() is False
    assert s.is_posthog_configured() is False
    assert s.is_smtp_configured() is False
    assert s.is_operator_configured() is False
    assert s.has_support_email() is False


def test_providers_are_on_when_all_their_settings_are_set(instance_env):
    s = instance_env(
        **_STRIPE_ENV,
        **_GOOGLE_ENV,
        **_SMTP_ENV,
        **_OPERATOR_ENV,
        SUPPORT_EMAIL="support@example.org",
        POSTHOG_PROJECT_API_KEY="phc_test",
    )

    assert s.is_stripe_billing_configured() is True
    assert s.is_google_configured() is True
    assert s.is_posthog_configured() is True
    assert s.is_smtp_configured() is True
    assert s.is_operator_configured() is True


@pytest.mark.parametrize(
    ("security", "port"),
    [("starttls", 587), ("tls", 465), ("none", 25)],
)
def test_smtp_port_defaults_to_the_security_modes_port(instance_env, security, port):
    s = instance_env(**_SMTP_ENV, SMTP_SECURITY=security)

    assert s.smtp_port() == port


def test_smtp_defaults_to_starttls_and_an_explicit_port_wins(instance_env):
    s = instance_env(**_SMTP_ENV, SMTP_PORT="2525")

    assert s.SMTP_SECURITY == "starttls"
    assert s.smtp_port() == 2525


@pytest.mark.parametrize(
    ("group", "unset"),
    [
        (_STRIPE_ENV, ["STRIPE_WEBHOOK_SECRET"]),
        (_STRIPE_ENV, ["STRIPE_PUBLISHABLE_KEY", "BILLING_PLAN_KEYS"]),
        (_STRIPE_ENV, ["STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET"]),
        (_GOOGLE_ENV, ["GOOGLE_CLIENT_SECRET"]),
        (_GOOGLE_ENV, ["GOOGLE_CLIENT_ID"]),
        (_SMTP_ENV, ["SMTP_HOST"]),
        (_SMTP_ENV, ["EMAIL_FROM"]),
    ],
)
def test_partly_configured_provider_fails_naming_each_missing_setting(instance_env, group, unset):
    partial = {key: value for key, value in group.items() if key not in unset}

    with pytest.raises(ValidationError) as excinfo:
        instance_env(**partial)

    message = str(excinfo.value)
    for key in unset:
        assert key in message


def test_a_settings_error_does_not_print_secret_values(instance_env):
    with pytest.raises(ValidationError) as excinfo:
        instance_env(
            TWITTERAPI_IO_API_KEY="tw-s3cret",
            STRIPE_SECRET_KEY="sk_s3cret",
        )

    message = str(excinfo.value)
    assert "STRIPE_PUBLISHABLE_KEY" in message
    assert "tw-s3cret" not in message
    assert "sk_s3cret" not in message


def test_support_email_alone_is_a_complete_instance(instance_env):
    s = instance_env(SUPPORT_EMAIL="support@example.org")

    assert s.has_support_email()
    assert not s.is_operator_configured()


def test_an_instance_may_set_neither_operator_details_nor_support_email(instance_env):
    s = instance_env()

    assert not s.has_support_email()
    assert not s.is_operator_configured()


def test_operator_details_with_support_email_turn_both_on(instance_env):
    s = instance_env(**_OPERATOR_ENV, SUPPORT_EMAIL="support@example.org")

    assert s.has_support_email()
    assert s.is_operator_configured()


def test_removed_operator_settings_left_in_the_env_still_boot(instance_env):
    s = instance_env(
        **_OPERATOR_ENV,
        SUPPORT_EMAIL="support@example.org",
        OPERATOR_ADDRESS="Via Roma 1, Milano, Italy",
        OPERATOR_REA="MI-123456",
        OPERATOR_SHARE_CAPITAL="€10,000",
        OPERATOR_PEC="example@pec.it",
    )

    assert s.is_operator_configured()


def test_operator_details_without_support_email_fail_naming_it(instance_env):
    # The company footer on the legal pages gives the support address as the Operator's contact.
    with pytest.raises(ValidationError, match="SUPPORT_EMAIL"):
        instance_env(**_OPERATOR_ENV)


def test_empty_plan_keys_count_as_unset(instance_env):
    stripe_without_plans = {**_STRIPE_ENV, "BILLING_PLAN_KEYS": "[]"}

    with pytest.raises(ValidationError, match="BILLING_PLAN_KEYS"):
        instance_env(**stripe_without_plans)


def test_settings_boot_without_optional_providers(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    for key in (
        "POSTHOG_ENABLED",
        "POSTHOG_PROJECT_API_KEY",
        "POSTHOG_PERSONAL_API_KEY",
        "POSTHOG_HOST",
    ):
        monkeypatch.delenv(key, raising=False)
    s = Settings()  # pyright: ignore[reportCallIssue]
    assert s.LLM_API_KEY is None
    assert s.LLM_BASE_URL == "https://openrouter.ai/api/v1"
    assert s.POSTHOG_ENABLED is False
    assert s.POSTHOG_PROJECT_API_KEY is None
    assert s.POSTHOG_HOST == "https://eu.i.posthog.com"


def test_an_empty_x_posts_cap_means_no_cap(monkeypatch):
    monkeypatch.setenv("X_POSTS_MONTHLY_CAP", "")
    s = Settings()  # pyright: ignore[reportCallIssue]
    assert s.X_POSTS_MONTHLY_CAP is None


def test_an_unset_x_posts_cap_defaults_to_100(monkeypatch):
    monkeypatch.delenv("X_POSTS_MONTHLY_CAP", raising=False)
    s = Settings()  # pyright: ignore[reportCallIssue]
    assert s.X_POSTS_MONTHLY_CAP == 100


def test_an_empty_link_posts_cap_means_no_cap_and_unset_defaults_to_10(monkeypatch):
    monkeypatch.setenv("X_LINK_POSTS_MONTHLY_CAP", "")
    assert Settings().X_LINK_POSTS_MONTHLY_CAP is None  # pyright: ignore[reportCallIssue]
    monkeypatch.delenv("X_LINK_POSTS_MONTHLY_CAP")
    assert Settings().X_LINK_POSTS_MONTHLY_CAP == 10  # pyright: ignore[reportCallIssue]


def test_jev_is_off_without_a_typesafe_key_and_pins_its_model(instance_env):
    s = instance_env()

    assert s.TYPESAFE_API_KEY is None
    assert s.TYPESAFE_MODEL == "jev-1.13.0"


def test_oauth_urls_derive_from_the_public_url(instance_env):
    s = instance_env(PUBLIC_URL="https://pumpkit.example.org/")

    assert s.oauth_issuer() == "https://pumpkit.example.org"
    assert s.mcp_url() == "https://pumpkit.example.org/api/v1/mcp"
    assert s.oauth_protected_resource_metadata_url() == (
        "https://pumpkit.example.org/.well-known/oauth-protected-resource/api/v1/mcp"
    )
    assert s.oauth_endpoint("authorize") == "https://pumpkit.example.org/api/v1/oauth/authorize"
    assert s.oauth_endpoint("revoke") == "https://pumpkit.example.org/api/v1/oauth/revoke"
    assert s.oauth_consent_page_url() == "https://pumpkit.example.org/oauth/consent"


def test_oauth_urls_keep_a_localhost_port(instance_env):
    s = instance_env(PUBLIC_URL="http://localhost:8080")

    assert s.oauth_issuer() == "http://localhost:8080"
    assert s.mcp_url() == "http://localhost:8080/api/v1/mcp"
    assert s.oauth_endpoint("token") == "http://localhost:8080/api/v1/oauth/token"
