"""
The `BillingGateway` port: every call Pumpkit makes to its billing provider.

Mediators depend on the port through `get_billing_gateway`; nothing else talks
to Stripe. Inputs and outputs are plain data, so no SDK object leaks out, and
the port never touches the database: persisting what it returns is the
mediator's job. Any provider failure is a `BillingProviderError`, which the
global error handler turns into a 502 with an `error_id`. A webhook that fails
verification is a `WebhookSignatureError` instead: the sender's fault, not the
provider's.

`StripeBillingGateway` is the production adapter and the only code that uses
the Stripe SDK. `FakeBillingGateway` records calls, returns configured results,
can be told to fail, and signs webhook payloads its own verifier accepts (tests
override the dependency with it).
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Optional, Protocol, Sequence, TypeVar

import stripe
from starlette.concurrency import run_in_threadpool
from stripe.params.checkout import SessionCreateParams as CheckoutSessionCreateParams

from app.core.config import settings


class BillingProviderError(Exception):
    """The billing provider failed or answered with something unusable."""


class WebhookSignatureError(Exception):
    """A webhook payload is malformed or its signature doesn't verify."""


@dataclass(frozen=True)
class CheckoutSession:
    """A hosted Subscription Checkout the User is sent to."""

    id: str
    url: str


@dataclass(frozen=True)
class Plan:
    """
    A Plan resolved from its key (the provider's price lookup key) to the
    provider's current price: an `amount` in the currency's minor units every
    `interval_count` `interval`s.
    """

    key: str
    price_id: str
    product_name: str
    amount: int
    currency: str
    interval: str
    interval_count: int


@dataclass(frozen=True)
class WebhookEvent:
    """A verified webhook event: its ID, its type and the object it is about."""

    id: str
    type: str
    data_object: dict[str, Any]


class BillingGateway(Protocol):
    async def create_customer(self, *, email: str, name: str, user_id: str) -> str:
        """Create the provider's customer record for a User and return its ID."""
        ...

    async def create_subscription_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        user_id: str,
        trial_period_days: Optional[int] = None,
    ) -> CheckoutSession:
        """Create a Subscription Checkout for one unit of `price_id`, with an optional Trial."""
        ...

    async def create_portal_url(self, *, customer_id: str) -> str:
        """Create a billing-portal session for the customer and return its URL."""
        ...

    async def list_plans(self, keys: Sequence[str]) -> list[Plan]:
        """
        Resolve Plan keys to the provider's current active recurring prices.
        Keys the provider doesn't know are left out; the order isn't guaranteed.
        """
        ...

    async def create_trial_subscription(
        self, *, customer_id: str, price_id: str, user_id: str, trial_period_days: int
    ) -> dict[str, Any]:
        """
        Start a Subscription in Trial without a card and return it as a dict.
        Only the `/stripe/trial` endpoint uses it; it goes when that endpoint does.
        """
        ...

    def verify_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent:
        """Verify a webhook payload and its signature, or raise `WebhookSignatureError`."""
        ...


def _plan(price: dict[str, Any]) -> Optional[Plan]:
    """A Stripe price as a Plan, or None when it can't be one (not recurring, no flat amount)."""
    recurring = price.get("recurring")
    if not price.get("lookup_key") or not recurring or price.get("unit_amount") is None:
        return None
    product = price.get("product")
    if not isinstance(product, dict) or product.get("deleted"):
        product = {}
    return Plan(
        key=price["lookup_key"],
        price_id=price["id"],
        product_name=product.get("name") or price.get("nickname") or price["lookup_key"],
        amount=price["unit_amount"],
        currency=price["currency"],
        interval=recurring["interval"],
        interval_count=recurring.get("interval_count") or 1,
    )


def _webhook_event(event: dict[str, Any]) -> WebhookEvent:
    try:
        return WebhookEvent(
            id=event["id"], type=event["type"], data_object=dict(event["data"]["object"])
        )
    except (KeyError, TypeError) as error:
        raise WebhookSignatureError("Webhook payload is not an event") from error


_T = TypeVar("_T")


class StripeBillingGateway:
    """Calls Stripe with its own client and API key, off the event loop, and returns plain data."""

    def __init__(self) -> None:
        self._client = stripe.StripeClient(settings.STRIPE_SECRET_KEY)

    async def _call(self, what: str, call: Callable[[], _T]) -> _T:
        try:
            return await run_in_threadpool(call)
        except stripe.StripeError as error:
            raise BillingProviderError(f"Stripe failed to {what}") from error

    async def create_customer(self, *, email: str, name: str, user_id: str) -> str:
        customer = await self._call(
            "create a customer",
            lambda: self._client.v1.customers.create(
                {"email": email, "name": name, "metadata": {"user_id": user_id}}
            ),
        )
        return customer.id

    async def create_subscription_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        user_id: str,
        trial_period_days: Optional[int] = None,
    ) -> CheckoutSession:
        params: CheckoutSessionCreateParams = {
            "mode": "subscription",
            "customer": customer_id,
            "client_reference_id": user_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": settings.STRIPE_CHECKOUT_SUCCESS_URL,
            "cancel_url": settings.STRIPE_CHECKOUT_CANCEL_URL,
            "allow_promotion_codes": True,
        }
        if trial_period_days is not None:
            params["subscription_data"] = {"trial_period_days": trial_period_days}
        session = await self._call(
            "create a Checkout", lambda: self._client.v1.checkout.sessions.create(params)
        )
        if not session.url:
            raise BillingProviderError(f"Stripe Checkout {session.id} has no URL")
        return CheckoutSession(id=session.id, url=session.url)

    async def create_portal_url(self, *, customer_id: str) -> str:
        portal = await self._call(
            "create a billing-portal session",
            lambda: self._client.v1.billing_portal.sessions.create(
                {"customer": customer_id, "return_url": settings.STRIPE_BILLING_PORTAL_RETURN_URL}
            ),
        )
        return portal.url

    async def list_plans(self, keys: Sequence[str]) -> list[Plan]:
        plans: list[Plan] = []
        # Stripe accepts at most 10 lookup keys per request.
        for start in range(0, len(keys), 10):
            batch = list(keys[start : start + 10])
            prices = await self._call(
                "list Plans",
                lambda: self._client.v1.prices.list(
                    {
                        "active": True,
                        "lookup_keys": batch,
                        "expand": ["data.product"],
                        "limit": 100,
                    }
                ),
            )
            plans.extend(plan for price in prices.data if (plan := _plan(price.to_dict())))
        return plans

    async def create_trial_subscription(
        self, *, customer_id: str, price_id: str, user_id: str, trial_period_days: int
    ) -> dict[str, Any]:
        subscription = await self._call(
            "start a Trial",
            lambda: self._client.v1.subscriptions.create(
                {
                    "customer": customer_id,
                    "items": [{"price": price_id}],
                    "trial_period_days": trial_period_days,
                    # With no card when the Trial ends, cancel instead of billing.
                    "trial_settings": {"end_behavior": {"missing_payment_method": "cancel"}},
                    # A card added later in the billing portal converts the Trial.
                    "payment_settings": {"save_default_payment_method": "on_subscription"},
                    "metadata": {"user_id": user_id},
                }
            ),
        )
        return subscription.to_dict()

    def verify_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent:
        # Pure HMAC work, no network: no need to leave the event loop.
        try:
            event = self._client.construct_event(
                payload=payload, sig_header=signature, secret=settings.STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.SignatureVerificationError) as error:
            raise WebhookSignatureError("Invalid Stripe webhook") from error
        return _webhook_event(event.to_dict())


@dataclass(frozen=True)
class CustomerCall:
    email: str
    name: str
    user_id: str


@dataclass(frozen=True)
class CheckoutCall:
    customer_id: str
    price_id: str
    user_id: str
    trial_period_days: Optional[int]


@dataclass(frozen=True)
class TrialCall:
    customer_id: str
    price_id: str
    user_id: str
    trial_period_days: int


@dataclass
class FakeBillingGateway:
    """
    A billing provider in memory. It records every call, answers with the
    configured results, and raises `BillingProviderError` from any method named
    in `fail_on`. Sign events with `signed_event`; its `verify_webhook` accepts
    only payloads signed with the same secret.
    """

    webhook_secret: str = "whsec_fake"
    fail_on: set[str] = field(default_factory=set)
    checkout_url: str = "https://checkout.test/session"
    portal_url: str = "https://billing.test/portal"
    plans: list[Plan] = field(default_factory=list)
    trial_subscription: dict[str, Any] = field(default_factory=dict)

    customers_created: list[CustomerCall] = field(default_factory=list)
    checkouts: list[CheckoutCall] = field(default_factory=list)
    portals: list[str] = field(default_factory=list)
    plan_lookups: list[list[str]] = field(default_factory=list)
    trials: list[TrialCall] = field(default_factory=list)

    def _maybe_fail(self, method: str) -> None:
        if method in self.fail_on:
            raise BillingProviderError(f"Fake billing gateway is set to fail {method}")

    async def create_customer(self, *, email: str, name: str, user_id: str) -> str:
        self._maybe_fail("create_customer")
        self.customers_created.append(CustomerCall(email=email, name=name, user_id=user_id))
        return f"cus_fake_{len(self.customers_created)}"

    async def create_subscription_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        user_id: str,
        trial_period_days: Optional[int] = None,
    ) -> CheckoutSession:
        self._maybe_fail("create_subscription_checkout")
        self.checkouts.append(
            CheckoutCall(
                customer_id=customer_id,
                price_id=price_id,
                user_id=user_id,
                trial_period_days=trial_period_days,
            )
        )
        return CheckoutSession(id=f"cs_fake_{len(self.checkouts)}", url=self.checkout_url)

    async def create_portal_url(self, *, customer_id: str) -> str:
        self._maybe_fail("create_portal_url")
        self.portals.append(customer_id)
        return self.portal_url

    async def list_plans(self, keys: Sequence[str]) -> list[Plan]:
        self._maybe_fail("list_plans")
        self.plan_lookups.append(list(keys))
        return [plan for plan in self.plans if plan.key in keys]

    async def create_trial_subscription(
        self, *, customer_id: str, price_id: str, user_id: str, trial_period_days: int
    ) -> dict[str, Any]:
        self._maybe_fail("create_trial_subscription")
        self.trials.append(
            TrialCall(
                customer_id=customer_id,
                price_id=price_id,
                user_id=user_id,
                trial_period_days=trial_period_days,
            )
        )
        return dict(self.trial_subscription)

    def signed_event(
        self, *, event_id: str, event_type: str, data_object: dict[str, Any]
    ) -> tuple[bytes, str]:
        """
        A webhook payload and the signature header the provider would send with
        it, in Stripe's shape and signing scheme, so `StripeBillingGateway`
        verifies it too when given the same secret.
        """
        event = {"id": event_id, "object": "event", "type": event_type}
        payload = json.dumps({**event, "data": {"object": data_object}}).encode()
        timestamp = str(int(time.time()))
        return payload, f"t={timestamp},v1={self._sign(timestamp, payload)}"

    def verify_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent:
        parts = dict(part.split("=", 1) for part in signature.split(",") if "=" in part)
        timestamp, received = parts.get("t"), parts.get("v1")
        if not timestamp or not received:
            raise WebhookSignatureError("Signature header is incomplete")
        if not hmac.compare_digest(received, self._sign(timestamp, payload)):
            raise WebhookSignatureError("Signature doesn't match the payload")
        try:
            event = json.loads(payload)
        except ValueError as error:
            raise WebhookSignatureError("Payload is not JSON") from error
        return _webhook_event(event)

    def _sign(self, timestamp: str, payload: bytes) -> str:
        signed = f"{timestamp}.".encode() + payload
        return hmac.new(self.webhook_secret.encode(), signed, hashlib.sha256).hexdigest()


@lru_cache
def get_billing_gateway() -> BillingGateway:
    """FastAPI dependency for the `BillingGateway` port."""
    return StripeBillingGateway()
