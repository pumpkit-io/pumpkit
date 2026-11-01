from typing import Literal, Optional

from pydantic import BaseModel

SignInMethod = Literal["magic_link", "google"]


class OperatorDetails(BaseModel):
    name: str
    vat_id: Optional[str] = None


class AnalyticsSettings(BaseModel):
    """What the browser needs to start PostHog once a visitor gives Analytics consent (ADR 0009)."""

    key: str
    host: str
    ui_host: str


class InstanceResponse(BaseModel):
    """What this Instance offers, read by the frontend at startup instead of build-time variables."""

    app_name: str
    sells_plans: bool
    sign_in_methods: list[SignInMethod]
    operator: Optional[OperatorDetails]
    support_email: Optional[str]
    analytics: Optional[AnalyticsSettings]
    x_connection: bool
    # Served by the backend so the copied URL is the one apps reach, not the browser's origin.
    mcp_url: str


class HealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
