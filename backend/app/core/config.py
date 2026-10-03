from typing import Literal, Optional

from pydantic_settings import BaseSettings

Environment = Literal["local", "dev", "stg", "prod"]
LoggingLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

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

    # Database
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
    PASSWORD_RESET_TOKEN_DURATION_HOURS: int
    PASSWORD_RESET_TOKEN_NUM_BYTES: int
    PASSWORD_MAX_LENGTH: int
    EMAIL_VERIFICATION_TOKEN_DURATION_HOURS: int
    EMAIL_VERIFICATION_TOKEN_NUM_BYTES: int
    EMAIL_VERIFICATION_COOKIE_DURATION_SECONDS: int
    MAGIC_LINK_TOKEN_DURATION_MINUTES: int
    MAGIC_LINK_TOKEN_NUM_BYTES: int

    # Google
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str
    GOOGLE_OAUTH_REDIRECT_URI: str
    GOOGLE_NONCE_TOKEN_NUM_BYTES: int
    GOOGLE_CODE_VERIFIER_TOKEN_NUM_BYTES: int
    GOOGLE_COOKIE_MAX_AGE_SECONDS: int
    GOOGLE_TOKEN_ENDPOINT_TIMEOUT_SECONDS: int

    # Resend
    RESEND_API_KEY: str
    RESEND_NOREPLY_ADDRESS: str
    RESEND_SUPPORT_ADDRESS: str

    # Stripe
    STRIPE_SECRET_KEY: str
    STRIPE_PUBLISHABLE_KEY: str
    STRIPE_WEBHOOK_SECRET: str
    STRIPE_CHECKOUT_SUCCESS_URL: str
    STRIPE_CHECKOUT_CANCEL_URL: str
    STRIPE_BILLING_PORTAL_RETURN_URL: str

    # OpenRouter (optional). When unset, app.core.openrouter raises
    # LLMNotConfiguredError on first use instead of failing at boot.
    OPENROUTER_API_KEY: Optional[str] = None

    # PostHog (optional). Disabled unless POSTHOG_ENABLED=true and a project key is set.
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
