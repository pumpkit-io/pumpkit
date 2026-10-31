from datetime import datetime
from typing import Annotated, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool

from pumpkit.billing.subscription_status import SubscriptionStatus


def _require_true(value: bool) -> bool:
    if not value:
        raise ValueError("must be true")
    return value


# A ticked box: JSON `true` only, never `false`, `1` or a string.
Accepted = Annotated[StrictBool, AfterValidator(_require_true)]


class TermsAcceptanceRequest(BaseModel):
    """
    The User's acceptance of the Terms (ADR 0010) that every checkout carries where the Instance
    has Terms (ADR 0011). The server decides everything else, so any other field is rejected.
    """

    model_config = ConfigDict(extra="forbid")

    terms_version: Optional[str] = None
    accepted_terms: Optional[Accepted] = None
    # Waives the consumer's 14-day withdrawal right once the paid period starts.
    requested_immediate_start: Optional[Accepted] = None
    # Approves the onerous clauses under arts. 1341 and 1342 of the Italian Civil Code.
    approved_specific_clauses: Optional[Accepted] = None


class CheckoutRequest(TermsAcceptanceRequest):
    """A Stripe checkout for a Plan, by key. The server decides the price, quantity and any Trial."""

    plan_key: str = Field(..., min_length=1)


class TopUpCheckoutRequest(TermsAcceptanceRequest):
    """A Stripe checkout for one Top-up, whose price and pack the server decides."""


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


class OfferedAllowanceResponse(BaseModel):
    """What each Allowance period of a Plan allows; a cap of None is no cap."""

    generations: Optional[int]
    x_posts: Optional[int]
    link_x_posts: Optional[int]


class OfferedTrialResponse(OfferedAllowanceResponse):
    """The Trial a first Subscription starts with: its length and its own Allowance."""

    days: int


class TopUpOfferResponse(OfferedAllowanceResponse):
    """The Top-up a paid-up User may buy: its price in minor units and what it adds."""

    amount: int
    currency: str


class PlansListResponse(BaseModel):
    """
    The Plans Pumpkit sells, in display order, and the Terms version a checkout must accept.
    `terms_version` is None where the Instance has no Operator details, so no Terms to accept.
    `trial` is None where the Instance offers no Trial; whether a User gets one is in `/billing/me`.
    """

    data: list[PlanResponse]
    terms_version: Optional[str]
    allowance: OfferedAllowanceResponse
    trial: Optional[OfferedTrialResponse]
    # None where the Instance sells no Top-ups; who may buy one is in `/usage`.
    top_up: Optional[TopUpOfferResponse] = None
