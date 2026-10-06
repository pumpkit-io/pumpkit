from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import SubscriptionStatus


class CheckoutRequest(BaseModel):
    """
    Request payload to create a Stripe checkout session. The client picks a
    Plan by key and nothing else: the server decides the price, the quantity
    and any Trial, so any other field is rejected.
    """

    model_config = ConfigDict(extra="forbid")

    plan_key: str = Field(..., min_length=1)


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


class BillingSubscriptionResponse(BaseModel):
    """
    The User's Subscription as Pumpkit's copy holds it.
    """

    status: SubscriptionStatus
    plan_key: Optional[str]
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool


class BillingMeResponse(BaseModel):
    """
    What the authenticated User holds and may do: their Subscription (Running,
    else `incomplete`, never Ended), whether they are Subscribed, whether they
    may subscribe, and the Trial a Checkout would start with.
    """

    subscription: Optional[BillingSubscriptionResponse]
    subscribed: bool
    may_subscribe: bool
    trial_days: Optional[int]


class PlanResponse(BaseModel):
    """
    A Plan a User can subscribe to: `amount` in the currency's minor units,
    charged every `interval_count` `interval`s.
    """

    key: str
    product_name: str
    amount: int
    currency: str
    interval: str
    interval_count: int


class PlansListResponse(BaseModel):
    """
    The Plans Pumpkit sells, in display order.
    """

    data: list[PlanResponse]
