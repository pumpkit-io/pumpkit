from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.subscription_status import SubscriptionStatus


class CheckoutRequest(BaseModel):
    """
    Request to create a Stripe checkout session for a Plan, by key only.
    The server decides the price, the quantity and any Trial, so any other field is rejected.
    """

    model_config = ConfigDict(extra="forbid")

    plan_key: str = Field(..., min_length=1)


class CheckoutResponse(BaseModel):
    """Stripe checkout session URL the frontend must redirect to."""

    url: str
    session_id: str


class BillingPortalResponse(BaseModel):
    """Stripe billing portal URL the frontend must redirect to."""

    url: str


class BillingSubscriptionResponse(BaseModel):
    """The User's Subscription as Pumpkit's copy holds it."""

    status: SubscriptionStatus
    plan_key: Optional[str]
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool


class BillingMeResponse(BaseModel):
    """
    What the authenticated User holds and may do.
    `subscription` is the Running one, else `incomplete`, never Ended; `trial_days` is the Trial a Checkout would start with.
    """

    subscription: Optional[BillingSubscriptionResponse]
    subscribed: bool
    may_subscribe: bool
    trial_days: Optional[int]


class PlanResponse(BaseModel):
    """A Plan a User can subscribe to: `amount` in minor units, charged every `interval_count` `interval`s."""

    key: str
    product_name: str
    amount: int
    currency: str
    interval: str
    interval_count: int


class PlansListResponse(BaseModel):
    """The Plans Pumpkit sells, in display order."""

    data: list[PlanResponse]
