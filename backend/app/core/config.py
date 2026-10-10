from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings

Environment = Literal["local", "dev", "stg", "prod"]
LoggingLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    # Environment
    ENV: Environment
    LOG_LEVEL: LoggingLevel = "INFO"
    APP_NAME: str

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
    JWT_ALGORITHM: str
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int
    JWT_ISSUER: str
    JWT_AUDIENCE: str
    COOKIE_MAX_AGE_SECONDS: int
    FERNET_ENCRYPTION_KEY: str
    MAGIC_LINK_TOKEN_DURATION_MINUTES: int
    MAGIC_LINK_TOKEN_NUM_BYTES: int

    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_OAUTH_REDIRECT_URI: str
    GOOGLE_NONCE_TOKEN_NUM_BYTES: int
    GOOGLE_CODE_VERIFIER_TOKEN_NUM_BYTES: int
    GOOGLE_COOKIE_MAX_AGE_SECONDS: int
    GOOGLE_TOKEN_ENDPOINT_TIMEOUT_SECONDS: int

    RESEND_API_KEY: str
    RESEND_NOREPLY_ADDRESS: str
    RESEND_SUPPORT_ADDRESS: str

    STRIPE_SECRET_KEY: str
    STRIPE_PUBLISHABLE_KEY: str
    STRIPE_WEBHOOK_SECRET: str
    STRIPE_CHECKOUT_SUCCESS_URL: str
    STRIPE_CHECKOUT_CANCEL_URL: str
    STRIPE_BILLING_PORTAL_RETURN_URL: str

    # The Plans Pumpkit sells, as Stripe price lookup keys, in display order.
    # Nothing else can be listed or bought.
    BILLING_PLAN_KEYS: list[str]
    # Days of Trial a User's first Subscription starts with; 0 turns Trials off.
    BILLING_TRIAL_PERIOD_DAYS: int = Field(ge=0)

    # Optional: when unset, app.core.openrouter raises LLMNotConfiguredError on use, not at boot.
    OPENROUTER_API_KEY: Optional[str] = None

    # Optional: when unset, app.core.x_reader raises XReaderNotConfiguredError on use, not at boot.
    TWITTERAPI_IO_API_KEY: Optional[str] = None

    # Optional: when unset, app.core.x_publisher raises XPublisherNotConfiguredError on use.
    X_CLIENT_ID: Optional[str] = None
    X_CLIENT_SECRET: Optional[str] = None
    # The frontend's X callback route, registered on the X developer app.
    X_REDIRECT_URI: Optional[str] = None

    # Optional: PostHog is disabled unless POSTHOG_ENABLED=true and a project key is set.
    POSTHOG_ENABLED: bool = False
    POSTHOG_PROJECT_API_KEY: Optional[str] = None
    POSTHOG_PERSONAL_API_KEY: Optional[str] = None
    POSTHOG_HOST: str = "https://eu.i.posthog.com"

    def is_env_local(self) -> bool:
        return self.ENV == "local"

    def is_env_development(self) -> bool:
        return self.ENV == "dev"

    def is_env_staging(self) -> bool:
        return self.ENV == "stg"

    def is_env_production(self) -> bool:
        return self.ENV == "prod"


settings: Settings = Settings()  # pyright: ignore[reportCallIssue]
