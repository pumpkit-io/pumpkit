import json
from typing import Annotated, Literal, Optional, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode

Environment = Literal["local", "dev", "stg", "prod"]
LoggingLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
SmtpSecurity = Literal["starttls", "tls", "none"]

_SMTP_DEFAULT_PORTS: dict[SmtpSecurity, int] = {"starttls": 587, "tls": 465, "none": 25}


class Settings(BaseSettings):
    # Environment
    ENV: Environment
    LOG_LEVEL: LoggingLevel = "INFO"
    APP_NAME: str = "Pumpkit"

    # Application
    BACKEND_URL: str
    BACKEND_PORT: int
    FRONTEND_URL: str
    FRONTEND_PORT: int
    CORS_ORIGINS: list[str]

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str
    POSTGRES_PORT: str
    POSTGRES_DB: str

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
    # Empty means the backend's own callback route under BACKEND_URL.
    GOOGLE_OAUTH_REDIRECT_URI: str = ""
    GOOGLE_NONCE_TOKEN_NUM_BYTES: int = 64
    GOOGLE_CODE_VERIFIER_TOKEN_NUM_BYTES: int = 64
    GOOGLE_COOKIE_MAX_AGE_SECONDS: int = 600
    GOOGLE_TOKEN_ENDPOINT_TIMEOUT_SECONDS: int = 30

    # Where the support link sends Users' email.
    SUPPORT_EMAIL: str

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
    # Empty means the frontend's billing pages under FRONTEND_URL.
    STRIPE_CHECKOUT_SUCCESS_URL: str = ""
    STRIPE_CHECKOUT_CANCEL_URL: str = ""
    STRIPE_BILLING_PORTAL_RETURN_URL: str = ""

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
    # The frontend's X callback route, registered on the X developer app.
    X_REDIRECT_URI: Optional[str] = None

    # How often the publisher process looks for due Scheduled posts.
    PUBLISHER_POLL_INTERVAL_SECONDS: int = Field(default=30, ge=1)
    # Each User's Scheduled posts per UTC calendar month of publish time (ADR 0006); None is no cap.
    SCHEDULED_POSTS_MONTHLY_CAP: Optional[int] = Field(default=100, ge=0)

    # Optional: PostHog is disabled unless POSTHOG_ENABLED=true and a project key is set.
    POSTHOG_ENABLED: bool = False
    POSTHOG_PROJECT_API_KEY: Optional[str] = None
    POSTHOG_PERSONAL_API_KEY: Optional[str] = None
    POSTHOG_HOST: str = "https://eu.i.posthog.com"

    @model_validator(mode="after")
    def _default_return_urls(self) -> Self:
        self.STRIPE_CHECKOUT_SUCCESS_URL = (
            self.STRIPE_CHECKOUT_SUCCESS_URL or f"{self.FRONTEND_URL}/billing/success"
        )
        self.STRIPE_CHECKOUT_CANCEL_URL = (
            self.STRIPE_CHECKOUT_CANCEL_URL or f"{self.FRONTEND_URL}/billing/cancelled"
        )
        self.STRIPE_BILLING_PORTAL_RETURN_URL = (
            self.STRIPE_BILLING_PORTAL_RETURN_URL or f"{self.FRONTEND_URL}/billing"
        )
        self.GOOGLE_OAUTH_REDIRECT_URI = (
            self.GOOGLE_OAUTH_REDIRECT_URI or f"{self.BACKEND_URL}/api/v1/oauth/google/callback"
        )
        return self

    @model_validator(mode="after")
    def _providers_all_or_nothing(self) -> Self:
        # A partly configured provider stops startup instead of failing when a User reaches it.
        for name, group in self._provider_groups().items():
            missing = [key for key, value in group.items() if not value]
            if missing and len(missing) < len(group):
                raise ValueError(f"{name} is partly configured; missing: {', '.join(missing)}")
        return self

    def _provider_groups(self) -> dict[str, dict[str, object]]:
        """Each optional provider's required settings; empty values count as unset."""
        return {
            "Stripe billing": {
                "STRIPE_SECRET_KEY": self.STRIPE_SECRET_KEY,
                "STRIPE_PUBLISHABLE_KEY": self.STRIPE_PUBLISHABLE_KEY,
                "STRIPE_WEBHOOK_SECRET": self.STRIPE_WEBHOOK_SECRET,
                "BILLING_PLAN_KEYS": self.BILLING_PLAN_KEYS,
            },
            "Google sign-in": {
                "GOOGLE_CLIENT_ID": self.GOOGLE_CLIENT_ID,
                "GOOGLE_CLIENT_SECRET": self.GOOGLE_CLIENT_SECRET,
            },
            "PostHog": {"POSTHOG_PROJECT_API_KEY": self.POSTHOG_PROJECT_API_KEY},
            "SMTP": {"SMTP_HOST": self.SMTP_HOST, "EMAIL_FROM": self.EMAIL_FROM},
        }

    def _is_configured(self, group: str) -> bool:
        return all(self._provider_groups()[group].values())

    def is_stripe_billing_configured(self) -> bool:
        return self._is_configured("Stripe billing")

    def is_google_configured(self) -> bool:
        return self._is_configured("Google sign-in")

    def is_posthog_configured(self) -> bool:
        return self._is_configured("PostHog")

    def is_smtp_configured(self) -> bool:
        return self._is_configured("SMTP")

    def smtp_port(self) -> int:
        return self.SMTP_PORT or _SMTP_DEFAULT_PORTS[self.SMTP_SECURITY]

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

    def is_env_local(self) -> bool:
        return self.ENV == "local"

    def is_env_development(self) -> bool:
        return self.ENV == "dev"

    def is_env_staging(self) -> bool:
        return self.ENV == "stg"

    def is_env_production(self) -> bool:
        return self.ENV == "prod"


settings: Settings = Settings()  # pyright: ignore[reportCallIssue]
