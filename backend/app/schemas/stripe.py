from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.db.models import SubscriptionStatus


class CheckoutRequest(BaseModel):
    """
    Request payload to create a Stripe checkout session.
    """

    price_id: str = Field(..., min_length=1)
    quantity: int = Field(default=1, ge=1)
    trial_period_days: Optional[int] = Field(default=None, ge=1)


class CheckoutResponse(BaseModel):
    """
    Response with the Stripe checkout session URL the frontend must redirect to.
    """

    url: str
    session_id: str


class BillingPortalResponse(BaseModel):
    """
    Response with the Stripe billing portal URL the frontend must redirect to.
    """

    url: str


class TrialRequest(BaseModel):
    """
    Request payload to start a cardless trial subscription.
    """

    price_id: str = Field(..., min_length=1)
    trial_period_days: int = Field(default=14, ge=1, le=365)


class TrialResponse(BaseModel):
    """
    Response after successfully starting a cardless trial.
    """

    subscription_id: str
    status: SubscriptionStatus
    trial_end: Optional[datetime]


class SubscriptionMeResponse(BaseModel):
    """
    Current subscription view for the authenticated user.
    """

    status: Optional[SubscriptionStatus]
    stripe_price_id: Optional[str]
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    is_active: bool


class PriceProduct(BaseModel):
    """
    Minimal view of a Stripe product attached to a price.
    """

    id: str
    name: Optional[str] = None
    description: Optional[str] = None


class PriceRecurring(BaseModel):
    """
    Minimal view of a recurring price's interval configuration.
    """

    interval: str
    interval_count: int


class PriceResponse(BaseModel):
    """
    Minimal view of a Stripe price for a pricing page.
    """

    id: str
    currency: str
    unit_amount: Optional[int]
    recurring: Optional[PriceRecurring] = None
    product: Optional[PriceProduct] = None


class PricesListResponse(BaseModel):
    """
    List of active Stripe prices.
    """

    data: list[PriceResponse]
