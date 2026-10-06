"""
The `BillingGateway` port: every call Pumpkit makes to its billing provider.

Its callers are the billing mediator, which gets it through
`get_billing_gateway`, and the Subscriptions module, which is handed it to sync
a customer; nothing else talks to Stripe. Inputs and outputs are plain data, so
no SDK object leaks out, and the port never touches the database: persisting
what it returns is its callers' job. Any provider failure is a `BillingProviderError`, which the
global error handler turns into a 502 with an `error_id`. A webhook that fails
verification is a `WebhookSignatureError` instead: the sender's fault, not the
provider's.

`StripeBillingGateway` is the production adapter and the only code that uses
the Stripe SDK. `FakeBillingGateway` records calls, returns configured results,
can be told to fail, holds each customer's Subscriptions, and signs webhook
payloads its own verifier accepts (tests override the dependency with it).
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable, Optional, Protocol, Sequence, TypeVar, cast, get_args

import stripe
from starlette.concurrency import run_in_threadpool
from stripe.params.checkout import SessionCreateParams as CheckoutSessionCreateParams

from app.core.config import settings
from app.core.subscription_status import SubscriptionStatus


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
class SubscriptionState:
    """
    A Subscription as the provider holds it now: its provider ID, status, price,
    Plan key (the price's lookup key, None when the price has none), the end of
    its current period, whether it cancels at that end, and when the provider
    created it.
    """

    id: str
    status: SubscriptionStatus
    price_id: Optional[str]
    plan_key: Optional[str]
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    created_at: datetime


@dataclass(frozen=True)
class WebhookEvent:
    """
    A verified webhook event: its ID, its type, and the customer it is about
    (None when its object names no customer). Webhooks are nudges (ADR 0004):
    nothing else of the event's payload leaves the gateway.
    """

    id: str
    type: str
    customer_id: Optional[str]


class BillingGateway(Protocol):
    async def create_customer(
        self, *, email: str, name: str, user_id: str, idempotency_key: str
    ) -> str:
        """
        Create the provider's customer record for a User and return its ID.
        Calls with the same `idempotency_key` create one customer: a repeat
        returns the first call's customer instead of a new one.
        """
        ...

    async def create_subscription_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        quantity: int,
        user_id: str,
        trial_period_days: Optional[int] = None,
    ) -> CheckoutSession:
        """Create a Subscription Checkout for `quantity` units of `price_id`, with an optional Trial."""
        ...

    async def expire_open_checkouts(self, *, customer_id: str) -> list[str]:
        """
        Expire every Checkout of the customer's that can still be completed, so
        none of them can start a Subscription any more, and return their IDs.
        """
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

    async def list_subscriptions(self, *, customer_id: str) -> list[SubscriptionState]:
        """Every Subscription the customer has, Ended ones included, as the provider holds it now."""
        ...

    async def cancel_subscription(self, *, subscription_id: str) -> None:
        """Cancel a Subscription now, so it Ends and can never run."""
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


def _first_item(subscription: dict[str, Any]) -> dict[str, Any]:
    """A Stripe subscription's first item, or an empty one when it has none."""
    items = (subscription.get("items") or {}).get("data") or []
    return items[0] if items else {}


def _timestamp(seconds: int) -> datetime:
    """A Stripe timestamp (Unix seconds) as an aware UTC datetime."""
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _subscription_state(subscription: dict[str, Any]) -> SubscriptionState:
    """A Stripe subscription as plain data, or `BillingProviderError` when it can't be one."""
    status = subscription.get("status")
    if status not in get_args(SubscriptionStatus):
        raise BillingProviderError(f"Stripe subscription has an unknown status: {status!r}")
    first_item = _first_item(subscription)
    price = first_item.get("price")
    if not isinstance(price, dict):
        price = {"id": price} if isinstance(price, str) else {}
    # Current Stripe API versions put the period end on the subscription items.
    period_end = subscription.get("current_period_end") or first_item.get("current_period_end")
    return SubscriptionState(
        id=subscription["id"],
        status=cast(SubscriptionStatus, status),
        price_id=price.get("id"),
        plan_key=price.get("lookup_key"),
        current_period_end=_timestamp(period_end) if period_end else None,
        cancel_at_period_end=bool(subscription.get("cancel_at_period_end")),
        created_at=_timestamp(subscription["created"]),
    )


def _customer_id(customer: Any) -> Optional[str]:
    """A Stripe `customer` field, sent as an ID or as an expanded customer, as the ID."""
    if isinstance(customer, str):
        return customer
    if isinstance(customer, dict):
        return customer.get("id")
    return None


def _webhook_event(event: dict[str, Any]) -> WebhookEvent:
    try:
        return WebhookEvent(
            id=event["id"],
            type=event["type"],
            customer_id=_customer_id(event["data"]["object"].get("customer")),
        )
    except (KeyError, TypeError, AttributeError) as error:
        raise WebhookSignatureError("Webhook payload is not an event") from error


_T = TypeVar("_T")


class StripeBillingGateway:
    """Calls Stripe with its own client and API key, off the event loop, and returns plain data."""

    def __init__(self, client: Optional[stripe.StripeClient] = None) -> None:
        self._client = client or stripe.StripeClient(settings.STRIPE_SECRET_KEY)

    async def _call(self, what: str, call: Callable[[], _T]) -> _T:
        try:
            return await run_in_threadpool(call)
        except stripe.StripeError as error:
            raise BillingProviderError(f"Stripe failed to {what}") from error

    async def create_customer(
        self, *, email: str, name: str, user_id: str, idempotency_key: str
    ) -> str:
        # Stripe replays the first response for a repeated key (for 24 hours).
        customer = await self._call(
            "create a customer",
            lambda: self._client.v1.customers.create(
                {"email": email, "name": name, "metadata": {"user_id": user_id}},
                {"idempotency_key": idempotency_key},
            ),
        )
        return customer.id

    async def create_subscription_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        quantity: int,
        user_id: str,
        trial_period_days: Optional[int] = None,
    ) -> CheckoutSession:
        params: CheckoutSessionCreateParams = {
            "mode": "subscription",
            "customer": customer_id,
            "client_reference_id": user_id,
            "line_items": [{"price": price_id, "quantity": quantity}],
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

    async def expire_open_checkouts(self, *, customer_id: str) -> list[str]:
        def expire_all() -> list[str]:
            sessions = self._client.v1.checkout.sessions.list(
                {"customer": customer_id, "status": "open", "limit": 100}
            )
            expired: list[str] = []
            for session in sessions.auto_paging_iter():
                self._client.v1.checkout.sessions.expire(session.id)
                expired.append(session.id)
            return expired

        # A session completed between the list and its expiry makes Stripe
        # refuse the expiry: that surfaces as a provider error too.
        return await self._call("expire open Checkouts", expire_all)

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

    async def list_subscriptions(self, *, customer_id: str) -> list[SubscriptionState]:
        def list_all() -> list[dict[str, Any]]:
            # Stripe leaves cancelled Subscriptions out unless asked for all of them.
            subscriptions = self._client.v1.subscriptions.list(
                {"customer": customer_id, "status": "all", "limit": 100}
            )
            return [subscription.to_dict() for subscription in subscriptions.auto_paging_iter()]

        return [
            _subscription_state(subscription)
            for subscription in await self._call("list Subscriptions", list_all)
        ]

    async def cancel_subscription(self, *, subscription_id: str) -> None:
        await self._call(
            "cancel a Subscription",
            lambda: self._client.v1.subscriptions.cancel(subscription_id),
        )

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
    idempotency_key: str


@dataclass(frozen=True)
class CheckoutCall:
    customer_id: str
    price_id: str
    quantity: int
    user_id: str
    trial_period_days: Optional[int]


@dataclass
class FakeBillingGateway:
    """
    A billing provider in memory. It records every call, answers with the
    configured results, and raises `BillingProviderError` from any method named
    in `fail_on`. Checkouts it creates stay open until `expire_open_checkouts`
    expires them. It holds each customer's Subscriptions: set one with
    `set_subscription` and `list_subscriptions` returns it; `cancel_subscription`
    turns it `canceled`. Sign events with `signed_event`; its `verify_webhook`
    accepts only payloads signed with the same secret.
    """

    webhook_secret: str = "whsec_fake"
    fail_on: set[str] = field(default_factory=set)
    checkout_url: str = "https://checkout.test/session"
    portal_url: str = "https://billing.test/portal"
    plans: list[Plan] = field(default_factory=list)

    customers_created: list[CustomerCall] = field(default_factory=list)
    checkouts: list[CheckoutCall] = field(default_factory=list)
    portals: list[str] = field(default_factory=list)
    plan_lookups: list[list[str]] = field(default_factory=list)
    expired_checkouts: list[str] = field(default_factory=list)
    cancelled_subscriptions: list[str] = field(default_factory=list)

    _open_checkouts: dict[str, str] = field(default_factory=dict, init=False)
    _subscriptions: dict[str, dict[str, SubscriptionState]] = field(
        default_factory=dict, init=False
    )
    _customers_by_idempotency_key: dict[str, str] = field(default_factory=dict, init=False)

    def _maybe_fail(self, method: str) -> None:
        if method in self.fail_on:
            raise BillingProviderError(f"Fake billing gateway is set to fail {method}")

    async def create_customer(
        self, *, email: str, name: str, user_id: str, idempotency_key: str
    ) -> str:
        self._maybe_fail("create_customer")
        self.customers_created.append(
            CustomerCall(email=email, name=name, user_id=user_id, idempotency_key=idempotency_key)
        )
        # Like Stripe, a repeated idempotency key returns the first customer.
        return self._customers_by_idempotency_key.setdefault(
            idempotency_key, f"cus_fake_{len(self._customers_by_idempotency_key) + 1}"
        )

    async def create_subscription_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        quantity: int,
        user_id: str,
        trial_period_days: Optional[int] = None,
    ) -> CheckoutSession:
        self._maybe_fail("create_subscription_checkout")
        self.checkouts.append(
            CheckoutCall(
                customer_id=customer_id,
                price_id=price_id,
                quantity=quantity,
                user_id=user_id,
                trial_period_days=trial_period_days,
            )
        )
        session_id = f"cs_fake_{len(self.checkouts)}"
        self._open_checkouts[session_id] = customer_id
        return CheckoutSession(id=session_id, url=self.checkout_url)

    async def expire_open_checkouts(self, *, customer_id: str) -> list[str]:
        self._maybe_fail("expire_open_checkouts")
        expired = [s for s, c in self._open_checkouts.items() if c == customer_id]
        for session_id in expired:
            del self._open_checkouts[session_id]
        self.expired_checkouts.extend(expired)
        return expired

    async def create_portal_url(self, *, customer_id: str) -> str:
        self._maybe_fail("create_portal_url")
        self.portals.append(customer_id)
        return self.portal_url

    async def list_plans(self, keys: Sequence[str]) -> list[Plan]:
        self._maybe_fail("list_plans")
        self.plan_lookups.append(list(keys))
        return [plan for plan in self.plans if plan.key in keys]

    def set_subscription(self, customer_id: str, subscription: SubscriptionState) -> None:
        """Make `subscription` what the provider holds now, replacing any with its ID."""
        self._subscriptions.setdefault(customer_id, {})[subscription.id] = subscription

    async def list_subscriptions(self, *, customer_id: str) -> list[SubscriptionState]:
        self._maybe_fail("list_subscriptions")
        return list(self._subscriptions.get(customer_id, {}).values())

    async def cancel_subscription(self, *, subscription_id: str) -> None:
        self._maybe_fail("cancel_subscription")
        self.cancelled_subscriptions.append(subscription_id)
        for subscriptions in self._subscriptions.values():
            if subscription := subscriptions.get(subscription_id):
                subscriptions[subscription_id] = replace(subscription, status="canceled")

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
