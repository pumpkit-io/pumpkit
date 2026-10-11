from typing import Literal, Optional

from pydantic import BaseModel

SignInMethod = Literal["magic_link", "google"]


class OperatorDetails(BaseModel):
    name: str
    address: str
    vat_id: Optional[str] = None
    rea: Optional[str] = None
    share_capital: Optional[str] = None
    pec: Optional[str] = None
    support_email: str


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
    analytics: Optional[AnalyticsSettings]
