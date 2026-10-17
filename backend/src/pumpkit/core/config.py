import json
from enum import StrEnum
from typing import Annotated, Literal, Optional, Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from pumpkit.core.db.urls import PostgresSsl

Environment = Literal["local", "prod"]
LoggingLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
SmtpSecurity = Literal["starttls", "tls", "none"]

_SMTP_DEFAULT_PORTS: dict[SmtpSecurity, int] = {"starttls": 587, "tls": 465, "none": 25}

BILLING_PAGE = "/billing"


class ProviderGroup(StrEnum):
    """An optional provider's settings group (ADR 0011); the value names it in startup errors."""

    STRIPE_BILLING = "Stripe billing"
    GOOGLE_SIGN_IN = "Google sign-in"
    POSTHOG = "PostHog"
    SMTP = "SMTP"
    OPERATOR_DETAILS = "Operator details"


class Settings(BaseSettings):
    # A settings error is logged at startup; its input values would include every secret.
    model_config = SettingsConfigDict(hide_input_in_errors=True)

    ENV: Environment = "prod"
    LOG_LEVEL: LoggingLevel = "INFO"
    APP_NAME: str = "Pumpkit"

    # The origin Users open, serving the frontend and the API under /api: every URL derives from it.
    PUBLIC_URL: str

    # Defaults reach the compose stack's bundled Postgres.
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: str = "5432"
    POSTGRES_DB: str = "postgres"
    POSTGRES_SSL: PostgresSsl = "disable"

    # Authentication
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    JWT_ISSUER: str = "pumpkit"
    JWT_AUDIENCE: str = "pumpkit-api"
    COOKIE_MAX_AGE_SECONDS: int = 2592000
    FERNET_ENCRYPTION_KEY: str
    MAGIC_LINK_TOKEN_DURATION_MINUTES: int = 15
    MAGIC_LINK_TOKEN_NUM_BYTES: int = 32
    # Comma-separated addresses and `@domain` entries that may sign in; empty lets anyone in.
    SIGN_UP_ALLOWLIST: str = ""

    # Optional group: Google sign-in is on only with both credentials.
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_NONCE_TOKEN_NUM_BYTES: int = 64
    GOOGLE_CODE_VERIFIER_TOKEN_NUM_BYTES: int = 64
    GOOGLE_COOKIE_MAX_AGE_SECONDS: int = 600
    GOOGLE_TOKEN_ENDPOINT_TIMEOUT_SECONDS: int = 30

    # Optional group: the company running this Instance, shown with its legal pages (ADR 0011).
    OPERATOR_NAME: Optional[str] = None
    OPERATOR_ADDRESS: Optional[str] = None
    OPERATOR_VAT_ID: Optional[str] = None
    OPERATOR_REA: Optional[str] = None
    OPERATOR_SHARE_CAPITAL: Optional[str] = None
    OPERATOR_PEC: Optional[str] = None

    # Optional: where the support link sends Users' email; unset hides the link.
    # Required with Operator details, since their company footer gives it as the contact address.
    SUPPORT_EMAIL: Optional[str] = None

    # Optional group: Magic links are emailed only with a host and a from address, else logged.
    SMTP_HOST: Optional[str] = None
    EMAIL_FROM: Optional[str] = None
    # None means the security mode's standard port.
    SMTP_PORT: Optional[int] = None
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_SECURITY: SmtpSecurity = "starttls"

    # Optional group: Stripe billing is on only with both keys, the webhook secret and Plan keys.
    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_PUBLISHABLE_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None

    # The Plans Pumpkit sells, as Stripe price lookup keys, in display order.
    # Nothing else can be listed or bought.
    BILLING_PLAN_KEYS: Annotated[list[str], NoDecode] = []
    # Days of Trial a User's first Subscription starts with; 0 turns Trials off.
    BILLING_TRIAL_PERIOD_DAYS: int = Field(default=14, ge=0)

    # Any OpenAI-compatible chat completions endpoint; OpenRouter by default.
    LLM_BASE_URL: str = "https://openrouter.ai/api/v1"
    # Optional: when unset, pumpkit.posts.llm_client raises LLMNotConfiguredError on use, not at boot.
    LLM_API_KEY: Optional[str] = None
    # The models the writing prompts were tuned against; each call can be re-pointed on its own.
    LLM_DRAFTING_MODEL: str = "openai/gpt-5.6-luna"
    LLM_HUMANIZING_MODEL: str = "openai/gpt-5.6-luna"
    LLM_REVISING_MODEL: str = "openai/gpt-5.6-luna"

    # Optional: when unset, pumpkit.authors.x_reader raises XReaderNotConfiguredError on use, not at boot.
    TWITTERAPI_IO_API_KEY: Optional[str] = None

    # Optional: when unset, pumpkit.x_connection.x_publisher raises XPublisherNotConfiguredError on use.
    X_CLIENT_ID: Optional[str] = None
    X_CLIENT_SECRET: Optional[str] = None

    # How often the publisher process looks for due Scheduled posts.
    PUBLISHER_POLL_INTERVAL_SECONDS: int = Field(default=30, ge=1)
    # Each User's Scheduled posts per UTC calendar month of publish time (ADR 0006); None is no cap.
    SCHEDULED_POSTS_MONTHLY_CAP: Optional[int] = Field(default=100, ge=0)

    # Optional group: the project key turns on browser analytics behind the consent banner.
    # Backend events also need POSTHOG_ENABLED=true, so dev and test Instances send none.
    POSTHOG_ENABLED: bool = False
    POSTHOG_PROJECT_API_KEY: Optional[str] = None
    POSTHOG_PERSONAL_API_KEY: Optional[str] = None
    POSTHOG_HOST: str = "https://eu.i.posthog.com"
    # Where the browser's PostHog links point, when POSTHOG_HOST is a relay rather than PostHog.
    POSTHOG_UI_HOST: str = "https://eu.posthog.com"

    @field_validator("PUBLIC_URL")
    @classmethod
    def _bare_origin(cls, value: str) -> str:
        origin = value.rstrip("/")
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.path:
            raise ValueError(
                f"PUBLIC_URL must be an http or https origin with no path, "
                f"like https://pumpkit.example.org; got {value!r}"
            )
        return origin

    @model_validator(mode="after")
    def _providers_all_or_nothing(self) -> Self:
        # A partly configured provider stops startup instead of failing when a User reaches it.
        for name, group in self._provider_groups().items():
            missing = [key for key, value in group.items() if not value]
            if missing and len(missing) < len(group):
                raise ValueError(f"{name} is partly configured; missing: {', '.join(missing)}")
        if self.is_operator_configured() and not self.has_support_email():
            raise ValueError(
                f"{ProviderGroup.OPERATOR_DETAILS} are set without SUPPORT_EMAIL, the contact "
                "address their company footer shows; missing: SUPPORT_EMAIL"
            )
        return self

    def _provider_groups(self) -> dict[ProviderGroup, dict[str, object]]:
        """Each optional provider's required settings; empty values count as unset."""
        return {
            ProviderGroup.STRIPE_BILLING: {
                "STRIPE_SECRET_KEY": self.STRIPE_SECRET_KEY,
                "STRIPE_PUBLISHABLE_KEY": self.STRIPE_PUBLISHABLE_KEY,
                "STRIPE_WEBHOOK_SECRET": self.STRIPE_WEBHOOK_SECRET,
                "BILLING_PLAN_KEYS": self.BILLING_PLAN_KEYS,
            },
            ProviderGroup.GOOGLE_SIGN_IN: {
                "GOOGLE_CLIENT_ID": self.GOOGLE_CLIENT_ID,
                "GOOGLE_CLIENT_SECRET": self.GOOGLE_CLIENT_SECRET,
            },
            ProviderGroup.POSTHOG: {"POSTHOG_PROJECT_API_KEY": self.POSTHOG_PROJECT_API_KEY},
            ProviderGroup.SMTP: {"SMTP_HOST": self.SMTP_HOST, "EMAIL_FROM": self.EMAIL_FROM},
            ProviderGroup.OPERATOR_DETAILS: {
                "OPERATOR_NAME": self.OPERATOR_NAME,
                "OPERATOR_ADDRESS": self.OPERATOR_ADDRESS,
            },
        }

    def _is_configured(self, group: ProviderGroup) -> bool:
        return all(self._provider_groups()[group].values())

    def is_stripe_billing_configured(self) -> bool:
        return self._is_configured(ProviderGroup.STRIPE_BILLING)

    def is_google_configured(self) -> bool:
        return self._is_configured(ProviderGroup.GOOGLE_SIGN_IN)

    def is_posthog_configured(self) -> bool:
        return self._is_configured(ProviderGroup.POSTHOG)

    def is_smtp_configured(self) -> bool:
        return self._is_configured(ProviderGroup.SMTP)

    def is_operator_configured(self) -> bool:
        return self._is_configured(ProviderGroup.OPERATOR_DETAILS)

    def has_support_email(self) -> bool:
        return bool(self.SUPPORT_EMAIL)

    def smtp_port(self) -> int:
        return self.SMTP_PORT or _SMTP_DEFAULT_PORTS[self.SMTP_SECURITY]

    def serves_https(self) -> bool:
        """Whether Users reach the Instance over HTTPS, which decides if cookies are `Secure`."""
        return urlsplit(self.PUBLIC_URL).scheme == "https"

    def frontend_url(self) -> str:
        return self.PUBLIC_URL

    def api_url(self) -> str:
        return f"{self.PUBLIC_URL}/api/v1"

    def cors_origins(self) -> list[str]:
        return [self.PUBLIC_URL]

    def google_oauth_redirect_uri(self) -> str:
        """The backend's callback route, registered on the Google OAuth client."""
        return f"{self.api_url()}/oauth/google/callback"

    def x_redirect_uri(self) -> str:
        """The frontend's callback route, registered on the X developer app."""
        return f"{self.frontend_url()}/oauth/x/callback"

    def stripe_checkout_success_url(self) -> str:
        return f"{self.frontend_url()}/billing/success"

    def stripe_checkout_cancel_url(self) -> str:
        return f"{self.frontend_url()}/billing/cancelled"

    def billing_page_url(self) -> str:
        """The web app page where a User subscribes or manages their Subscription."""
        return f"{self.frontend_url()}{BILLING_PAGE}"

    def stripe_billing_portal_return_url(self) -> str:
        return self.billing_page_url()

    @field_validator("BILLING_PLAN_KEYS", mode="before")
    @classmethod
    def _parse_plan_keys(cls, value: object) -> object:
        # Decoded here, not by pydantic-settings, so an empty `.env` line means no Plans.
        if isinstance(value, str):
            return json.loads(value) if value.strip() else []
        return value

    @field_validator("SCHEDULED_POSTS_MONTHLY_CAP", "SMTP_PORT", mode="before")
    @classmethod
    def _empty_int_is_none(cls, value: object) -> object:
        # Pydantic would reject the empty string an `.env` line leaves for an int.
        return None if value == "" else value


settings: Settings = Settings()  # pyright: ignore[reportCallIssue]
