"""
The `BillingGateway` port: every call Pumpkit makes to its billing provider.

Only the billing mediator (via `get_billing_gateway`) and the Subscriptions
module (to sync a customer) call it. It takes and returns plain data and never
touches the database: persisting results is the callers' job.

A provider failure is a `BillingProviderError` (a 502 with an `error_id`); a
webhook that fails verification is a `WebhookSignatureError`, the sender's fault.

`StripeBillingGateway` is the only Stripe SDK user; tests swap in `FakeBillingGateway`.
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

from pumpkit.billing.allowance import months_after
from pumpkit.billing.subscription_status import SubscriptionStatus
from pumpkit.core.config import settings
from pumpkit.core.errors import AppError
from pumpkit.core.logging import logger
from pumpkit.core.time import Clock, system_clock


class BillingProviderError(AppError):
    """The billing provider failed or answered with something unusable."""

    status_code = 502
    public_detail = "Billing is unavailable right now. Please try again later."
    reported = True


class DeferralRefused(BillingProviderError):
    """The provider definitely rejected the change without applying it."""


class WebhookSignatureError(Exception):
    """A webhook payload is malformed or its signature doesn't verify."""


@dataclass(frozen=True)
class CheckoutSession:
    """A hosted Subscription Checkout the User is sent to."""

    id: str
    url: str


@dataclass(frozen=True)
class PaidSignupSetup:
    id: str
    customer_id: str
    operation_id: str
    status: str
    url: Optional[str] = None
    payment_method_id: Optional[str] = None
    setup_status: Optional[str] = None
    setup_customer_id: Optional[str] = None
    payment_method_customer_id: Optional[str] = None
    usage: Optional[str] = None


@dataclass(frozen=True)
class Plan:
    """
    A Plan key (the provider's price lookup key) resolved to its current price:
    `amount` in the currency's minor units every `interval_count` `interval`s.
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
    A Subscription as the provider holds it now. `plan_key` is the price's
    lookup key, None when the price has none. `billing_cycle_anchor` is when its
    paid periods start: the Trial's end after a Trial, else its start. `cancel_at`
    is when a cancelled one ends, None while it renews.
    """

    id: str
    status: SubscriptionStatus
    price_id: Optional[str]
    plan_key: Optional[str]
    current_period_end: Optional[datetime]
    created_at: datetime
    cancel_at: Optional[datetime] = None
    trial_start: Optional[datetime] = None
    trial_end: Optional[datetime] = None
    billing_cycle_anchor: Optional[datetime] = None
    has_pending_update: bool = False
    schedule_id: Optional[str] = None
    latest_invoice_status: Optional[str] = None
    item_id: Optional[str] = None
    item_count: int = 0
    interval: Optional[str] = None
    interval_count: Optional[int] = None
    billing_mode: Optional[str] = None
    current_period_start: Optional[datetime] = None
    paid_current_period: bool = False
    paused: bool = False
    coupon_operation: Optional[str] = None
    paid_signup_operation: Optional[str] = None


@dataclass(frozen=True)
class OneOffPrice:
    """A price lookup key resolved to its current one-off price, in the currency's minor units."""

    key: str
    price_id: str
    amount: int
    currency: str


@dataclass(frozen=True)
class TopUpPurchase:
    """
    A paid Top-up Checkout as the provider holds it now. `reversed` when its payment was refunded,
    in whole or in part, or disputed: what is left of the Top-up is then removed.
    """

    checkout_session_id: str
    paid_at: datetime
    reversed: bool
    charge_id: Optional[str] = None


@dataclass(frozen=True)
class WebhookEvent:
    """
    A verified webhook event. Webhooks are nudges (ADR 0004): nothing else of
    the payload leaves the gateway. A dispute names no customer, only its `charge_id`.
    """

    id: str
    type: str
    customer_id: Optional[str]
    charge_id: Optional[str] = None


class BillingGateway(Protocol):
    async def create_customer(
        self, *, email: str, name: str, user_id: str, idempotency_key: str
    ) -> str:
        """
        Create the provider's customer for a User and return its ID. A repeated
        `idempotency_key` returns the first call's customer instead of a new one.
        """
        ...

    async def find_user_customers(self, *, user_id: str) -> list[str]: ...

    async def create_subscription_checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        quantity: int,
        user_id: str,
        trial_period_days: Optional[int] = None,
    ) -> CheckoutSession: ...

    async def create_paid_signup_setup(
        self,
        *,
        customer_id: str,
        user_id: str,
        operation_id: str,
        currency: str,
        expires_at: datetime,
    ) -> PaidSignupSetup: ...

    async def list_paid_signup_setups(self, *, customer_id: str) -> list[PaidSignupSetup]: ...

    async def expire_paid_signup_setup(self, *, session_id: str) -> None: ...

    async def create_paid_signup(
        self,
        *,
        customer_id: str,
        price_id: str,
        payment_method_id: str,
        operation_id: str,
        first_payment_at: datetime,
    ) -> None: ...

    async def expire_open_checkouts(self, *, customer_id: str) -> list[str]:
        """Expire the customer's open Checkouts so none can start a Subscription; return IDs."""
        ...

    async def create_portal_url(self, *, customer_id: str) -> str: ...

    async def list_plans(self, keys: Sequence[str]) -> list[Plan]:
        """
        Resolve Plan keys to the provider's current active recurring prices.
        Keys the provider doesn't know are left out; the order isn't guaranteed.
        """
        ...

    async def list_subscriptions(self, *, customer_id: str) -> list[SubscriptionState]:
        """Every Subscription the customer has, Ended ones included."""
        ...

    async def has_open_subscription_checkout(self, *, customer_id: str) -> bool: ...

    async def has_pending_checkout(self, *, customer_id: str) -> bool: ...

    async def has_unsettled_invoices(self, *, customer_id: str) -> bool:
        """Whether any customer invoice still requires settlement, including an older debt."""
        ...

    async def cancel_subscription(self, *, subscription_id: str) -> None:
        """Cancel a Subscription now, so it Ends and can never run."""
        ...

    async def defer_renewal(
        self, *, subscription_id: str, target: datetime, operation_id: str
    ) -> None: ...

    async def cancel_renewal(self, *, subscription_id: str, ends_at: datetime) -> None: ...

    async def end_trial(self, *, subscription_id: str) -> Optional[str]:
        """
        End a trialing Subscription's Trial now: the provider charges the first period at once and
        moves the billing cycle anchor to now. A failed charge leaves it past due, not an error.

        Returns the provider's page where the User authenticates the first charge when it waits
        for that (3D Secure), else None. Repeating the update after the Trial leaves its dates
        and invoice unchanged. An error can follow a successful update; the caller must sync.
        """
        ...

    def verify_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent:
        """Verify a webhook payload and its signature, or raise `WebhookSignatureError`."""
        ...

    async def get_one_off_price(self, key: str) -> Optional[OneOffPrice]:
        """The active one-off price with lookup key `key`, or None when the provider has none."""
        ...

    async def create_top_up_checkout(
        self, *, customer_id: str, price_id: str, user_id: str
    ) -> CheckoutSession:
        """A hosted Checkout that takes one payment for one Top-up."""
        ...

    async def list_top_ups(self, *, customer_id: str) -> list[TopUpPurchase]:
        """Every paid Top-up Checkout of the customer, refunded and disputed ones included."""
        ...

    async def get_charge_customer(self, *, charge_id: str) -> Optional[str]:
        """The customer a charge belongs to, for events that name only the charge."""
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


def _optional_timestamp(seconds: Optional[int]) -> Optional[datetime]:
    return _timestamp(seconds) if seconds else None


def _subscription_state(subscription: dict[str, Any]) -> SubscriptionState:
    """A Stripe subscription as plain data, or `BillingProviderError` when it can't be one."""
    status = subscription.get("status")
    if status not in get_args(SubscriptionStatus):
        raise BillingProviderError(f"Stripe subscription has an unknown status: {status!r}")
    first_item = _first_item(subscription)
    price = first_item.get("price")
    if not isinstance(price, dict):
        price = {"id": price} if isinstance(price, str) else {}
    price = cast(dict[str, Any], price)
    # Current Stripe API versions put the period end on the subscription items.
    period_end = subscription.get("current_period_end") or first_item.get("current_period_end")
    # Flexible billing mode records a cancellation as `cancel_at`, the older way as a flag.
    cancel_at = subscription.get("cancel_at") or (
        period_end if subscription.get("cancel_at_period_end") else None
    )
    return SubscriptionState(
        id=subscription["id"],
        status=cast(SubscriptionStatus, status),
        price_id=price.get("id"),
        plan_key=price.get("lookup_key"),
        current_period_end=_optional_timestamp(period_end),
        created_at=_timestamp(subscription["created"]),
        cancel_at=_optional_timestamp(cancel_at),
        trial_start=_optional_timestamp(subscription.get("trial_start")),
        trial_end=_optional_timestamp(subscription.get("trial_end")),
        billing_cycle_anchor=_optional_timestamp(subscription.get("billing_cycle_anchor")),
        has_pending_update=subscription.get("pending_update") is not None,
        schedule_id=_customer_id(subscription.get("schedule")),
        item_id=first_item.get("id"),
        item_count=len(subscription.get("items", {}).get("data", []))
        if not subscription.get("items", {}).get("has_more") and first_item.get("quantity") == 1
        else 0,
        interval=price.get("recurring", {}).get("interval"),
        interval_count=price.get("recurring", {}).get("interval_count"),
        billing_mode=(subscription.get("billing_mode") or {}).get("type"),
        current_period_start=_optional_timestamp(
            first_item.get("current_period_start") or subscription.get("current_period_start")
        ),
        paused=bool(subscription.get("pause_collection")),
        coupon_operation=subscription.get("metadata", {}).get("pumpkit_coupon_operation"),
        paid_signup_operation=subscription.get("metadata", {}).get("pumpkit_paid_signup"),
        paid_current_period=_paid_current_period(subscription, first_item),
        latest_invoice_status=(
            subscription["latest_invoice"].get("status") or "unknown"
            if isinstance(subscription.get("latest_invoice"), dict)
            else "unknown"
            if subscription.get("latest_invoice")
            else None
        ),
    )


def _paid_signup_setup(session: dict[str, Any]) -> PaidSignupSetup:
    intent = session.get("setup_intent")
    intent = intent if isinstance(intent, dict) else {}
    method = intent.get("payment_method")
    method = method if isinstance(method, dict) else {}
    customer = _customer_id(session.get("customer"))
    operation = session.get("metadata", {}).get("pumpkit_paid_signup")
    if not customer or not operation or session.get("mode") != "setup":
        raise BillingProviderError("Stripe returned an unrelated setup Checkout")
    if intent and intent.get("metadata", {}).get("pumpkit_paid_signup") != operation:
        raise BillingProviderError("Stripe setup intent attribution differs")
    return PaidSignupSetup(
        id=session["id"],
        customer_id=customer,
        operation_id=operation,
        status=session.get("status", "unknown"),
        url=session.get("url"),
        payment_method_id=method.get("id"),
        setup_status=intent.get("status"),
        setup_customer_id=_customer_id(intent.get("customer")),
        payment_method_customer_id=_customer_id(method.get("customer")),
        usage=intent.get("usage"),
    )


def _paid_current_period(subscription: dict[str, Any], item: dict[str, Any]) -> bool:
    invoice = subscription.get("latest_invoice")
    if (
        not isinstance(invoice, dict)
        or invoice.get("status") != "paid"
        or invoice.get("amount_paid", 0) <= 0
        or invoice.get("amount_remaining", 0) != 0
    ):
        return False
    start = item.get("current_period_start") or subscription.get("current_period_start")
    end = item.get("current_period_end") or subscription.get("current_period_end")
    return bool(
        start
        and end
        and any(
            line.get("period", {}).get("start") == start
            and line.get("period", {}).get("end") == end
            and line.get("amount", 0) > 0
            and (
                line.get("subscription_item")
                or (line.get("parent") or {})
                .get("subscription_item_details", {})
                .get("subscription_item")
            )
            == item.get("id")
            for line in invoice.get("lines", {}).get("data", [])
        )
    )


def _customer_id(customer: Any) -> Optional[str]:
    """A Stripe `customer` field, sent as an ID or as an expanded customer, as the ID."""
    if isinstance(customer, str):
        return customer
    if isinstance(customer, dict):
        return customer.get("id")
    return None


# Marks the Checkouts that buy a Top-up among a customer's Checkouts.
_TOP_UP_METADATA = {"pumpkit_purchase": "top_up"}


def _one_off_price(price: dict[str, Any]) -> Optional[OneOffPrice]:
    if (
        not price.get("lookup_key")
        or price.get("type") != "one_time"
        or price.get("unit_amount") is None
    ):
        return None
    return OneOffPrice(
        key=price["lookup_key"],
        price_id=price["id"],
        amount=price["unit_amount"],
        currency=price["currency"],
    )


def _top_up_purchase(session: dict[str, Any]) -> Optional[TopUpPurchase]:
    """A Checkout as a paid Top-up, or None when it buys something else or isn't paid yet."""
    metadata = session.get("metadata") or {}
    if (
        session.get("mode") != "payment"
        or metadata.get("pumpkit_purchase") != _TOP_UP_METADATA["pumpkit_purchase"]
        or session.get("payment_status") != "paid"
    ):
        return None
    intent = session.get("payment_intent")
    charge = intent.get("latest_charge") if isinstance(intent, dict) else None
    if not isinstance(charge, dict):
        charge = {}
    return TopUpPurchase(
        checkout_session_id=session["id"],
        paid_at=_timestamp(charge.get("created") or session["created"]),
        reversed=bool(charge.get("amount_refunded") or charge.get("disputed")),
        charge_id=charge.get("id"),
    )


def _webhook_event(event: dict[str, Any]) -> WebhookEvent:
    try:
        data_object = event["data"]["object"]
        charge = data_object.get("charge")
        return WebhookEvent(
            id=event["id"],
            type=event["type"],
            customer_id=_customer_id(data_object.get("customer")),
            charge_id=charge if isinstance(charge, str) else None,
        )
    except (KeyError, TypeError, AttributeError) as error:
        raise WebhookSignatureError("Webhook payload is not an event") from error


_T = TypeVar("_T")


def stripe_client(**options: Any) -> stripe.StripeClient:
    """A Stripe client with this Instance's API key, calling `STRIPE_API_URL` when one is set."""
    if settings.STRIPE_API_URL:
        options["base_addresses"] = {"api": settings.STRIPE_API_URL}
    # Without Stripe billing configured, Stripe rejects every call made with the empty key.
    return stripe.StripeClient(settings.STRIPE_SECRET_KEY or "", **options)


class StripeBillingGateway:
    """Calls Stripe with its own client and API key, off the event loop, and returns plain data."""

    def __init__(self, client: Optional[stripe.StripeClient] = None) -> None:
        self._client = client or stripe_client()

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

    async def find_user_customers(self, *, user_id: str) -> list[str]:
        def read() -> list[str]:
            customers = self._client.v1.customers.list({"limit": 100})
            return [
                c.id
                for c in customers.auto_paging_iter()
                if c.to_dict().get("metadata", {}).get("user_id") == user_id
            ]

        return await self._call("find the signup customer", read)

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
            "success_url": settings.stripe_checkout_success_url(),
            "cancel_url": settings.stripe_checkout_cancel_url(),
            "allow_promotion_codes": True,
            "automatic_tax": {"enabled": True},
            "tax_id_collection": {"enabled": True},
            "customer_update": {"address": "auto", "name": "auto"},
            # Keep the Instance the seller, charging tax through Stripe Tax: Stripe turns on
            # Managed Payments (Stripe as merchant of record) by default for new accounts.
            "managed_payments": {"enabled": False},
        }
        if trial_period_days is not None:
            params["subscription_data"] = {"trial_period_days": trial_period_days}
        session = await self._call(
            "create a Checkout", lambda: self._client.v1.checkout.sessions.create(params)
        )
        if not session.url:
            raise BillingProviderError(f"Stripe Checkout {session.id} has no URL")
        return CheckoutSession(id=session.id, url=session.url)

    async def create_paid_signup_setup(
        self,
        *,
        customer_id: str,
        user_id: str,
        operation_id: str,
        currency: str,
        expires_at: datetime,
    ) -> PaidSignupSetup:
        metadata = {"pumpkit_paid_signup": operation_id}
        params: CheckoutSessionCreateParams = {
            "mode": "setup",
            "customer": customer_id,
            "client_reference_id": user_id,
            "currency": currency,
            "payment_method_types": ["card"],
            "billing_address_collection": "required",
            "customer_update": {"address": "auto", "name": "auto"},
            "tax_id_collection": {"enabled": True},
            "metadata": metadata,
            "setup_intent_data": {"metadata": metadata},
            "expires_at": int(expires_at.timestamp()),
            "success_url": settings.billing_page_url(),
            "cancel_url": settings.billing_page_url(),
        }
        session = await self._call(
            "create future signup Checkout",
            lambda: self._client.v1.checkout.sessions.create(
                params, {"idempotency_key": f"{operation_id}:setup"}
            ),
        )
        return _paid_signup_setup(session.to_dict())

    async def list_paid_signup_setups(self, *, customer_id: str) -> list[PaidSignupSetup]:
        def read() -> list[PaidSignupSetup]:
            sessions = self._client.v1.checkout.sessions.list(
                {"customer": customer_id, "limit": 100}
            )
            result = []
            for session in sessions.auto_paging_iter():
                data = session.to_dict()
                if data.get("mode") != "setup" or not data.get("metadata", {}).get(
                    "pumpkit_paid_signup"
                ):
                    continue
                current = self._client.v1.checkout.sessions.retrieve(
                    session.id, {"expand": ["setup_intent.payment_method"]}
                )
                result.append(_paid_signup_setup(current.to_dict()))
            return result

        return await self._call("read future signup Checkouts", read)

    async def expire_paid_signup_setup(self, *, session_id: str) -> None:
        await self._call(
            "expire future signup Checkout",
            lambda: self._client.v1.checkout.sessions.expire(session_id),
        )

    async def create_paid_signup(
        self,
        *,
        customer_id: str,
        price_id: str,
        payment_method_id: str,
        operation_id: str,
        first_payment_at: datetime,
    ) -> None:
        if first_payment_at.timestamp() <= time.time():
            raise DeferralRefused("The accepted first payment date has passed")
        try:
            await run_in_threadpool(
                lambda: self._client.v1.subscriptions.create(
                    {
                        "customer": customer_id,
                        "items": [{"price": price_id, "quantity": 1}],
                        "default_payment_method": payment_method_id,
                        "trial_end": int(first_payment_at.timestamp()),
                        "automatic_tax": {"enabled": True},
                        "proration_behavior": "none",
                        "payment_behavior": "error_if_incomplete",
                        "metadata": {"pumpkit_paid_signup": operation_id},
                    },
                    {"idempotency_key": f"{operation_id}:subscription"},
                )
            )
        except stripe.InvalidRequestError as error:
            raise DeferralRefused("Stripe refused the exact future signup") from error
        except stripe.StripeError as error:
            raise BillingProviderError("Stripe failed to create future signup") from error

    async def has_open_subscription_checkout(self, *, customer_id: str) -> bool:
        def has_open() -> bool:
            sessions = self._client.v1.checkout.sessions.list(
                {"customer": customer_id, "status": "open", "limit": 100}
            )
            return any(
                session.to_dict().get("mode") == "subscription"
                for session in sessions.auto_paging_iter()
            )

        return await self._call("check pending subscription Checkout", has_open)

    async def has_pending_checkout(self, *, customer_id: str) -> bool:
        def pending() -> bool:
            sessions = self._client.v1.checkout.sessions.list(
                {
                    "customer": customer_id,
                    "expand": ["data.payment_intent", "data.setup_intent"],
                    "limit": 100,
                }
            )
            for session in sessions.auto_paging_iter():
                state = session.to_dict()
                if state.get("status") == "expired":
                    continue
                if state.get("mode") == "setup" and state.get("status") == "complete":
                    setup = state.get("setup_intent")
                    if isinstance(setup, dict) and setup.get("status") in {"succeeded", "canceled"}:
                        continue
                intent = state.get("payment_intent")
                if (
                    state.get("status") == "complete"
                    and state.get("mode") in {"payment", "subscription"}
                    and state.get("payment_status") == "unpaid"
                    and isinstance(intent, dict)
                    and intent.get("status") == "canceled"
                ):
                    continue
                if (
                    state.get("status") != "complete"
                    or state.get("mode") not in {"payment", "subscription"}
                    or state.get("payment_status") not in {"paid", "no_payment_required"}
                ):
                    return True
            return False

        return await self._call("check pending Checkout", pending)

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
                {"customer": customer_id, "return_url": settings.stripe_billing_portal_return_url()}
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
                {
                    "customer": customer_id,
                    "status": "all",
                    "limit": 100,
                    "expand": ["data.latest_invoice"],
                }
            )
            return [subscription.to_dict() for subscription in subscriptions.auto_paging_iter()]

        return [
            _subscription_state(subscription)
            for subscription in await self._call("list Subscriptions", list_all)
        ]

    async def has_unsettled_invoices(self, *, customer_id: str) -> bool:
        def unsettled() -> bool:
            invoices = self._client.v1.invoices.list({"customer": customer_id, "limit": 100})
            for invoice in invoices.auto_paging_iter():
                state = invoice.to_dict()
                if state.get("status") not in {"paid", "void"}:
                    return True
            return False

        return await self._call("check invoice settlement", unsettled)

    async def cancel_subscription(self, *, subscription_id: str) -> None:
        await self._call(
            "cancel a Subscription",
            lambda: self._client.v1.subscriptions.cancel(subscription_id),
        )

    async def defer_renewal(
        self, *, subscription_id: str, target: datetime, operation_id: str
    ) -> None:
        try:
            await run_in_threadpool(
                self._client.v1.subscriptions.update,
                subscription_id,
                {
                    "trial_end": int(target.timestamp()),
                    "proration_behavior": "none",
                    "metadata": {"pumpkit_coupon_operation": operation_id},
                },
                {"idempotency_key": "coupon-deferral-" + operation_id},
            )
        except stripe.InvalidRequestError as exc:
            raise DeferralRefused("Stripe refused the coupon deferral") from exc
        except stripe.StripeError as exc:
            raise BillingProviderError("Stripe coupon deferral outcome is uncertain") from exc

    async def cancel_renewal(self, *, subscription_id: str, ends_at: datetime) -> None:
        await self._call(
            "cancel future renewal",
            lambda: self._client.v1.subscriptions.update(
                subscription_id,
                {"cancel_at": int(ends_at.timestamp()), "proration_behavior": "none"},
            ),
        )

    async def end_trial(self, *, subscription_id: str) -> Optional[str]:
        subscription = await self._call(
            "end a Trial",
            lambda: self._client.v1.subscriptions.update(
                subscription_id,
                # `allow_incomplete` keeps the update when the charge fails: Stripe makes the
                # Subscription past due instead of refusing the change.
                {
                    "trial_end": "now",
                    "payment_behavior": "allow_incomplete",
                    "expand": ["latest_invoice"],
                },
            ),
        )
        invoice = subscription.to_dict().get("latest_invoice")
        if not isinstance(invoice, dict) or invoice.get("status") != "open":
            return None
        try:
            payments = await self._call(
                "list a first charge's payments",
                lambda: self._client.v1.invoice_payments.list(
                    {
                        "invoice": invoice["id"],
                        "status": "open",
                        "expand": ["data.payment.payment_intent"],
                    }
                ),
            )
        except BillingProviderError:
            # The Trial has ended either way, so the caller still syncs; it only loses the link.
            logger.warning("Couldn't tell why invoice %s is unpaid", invoice["id"], exc_info=True)
            return None
        for payment in payments.data:
            intent = payment.to_dict().get("payment", {}).get("payment_intent")
            if isinstance(intent, dict) and intent.get("status") == "requires_action":
                return invoice.get("hosted_invoice_url")
        return None

    def verify_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent:
        # Pure HMAC work, no network: no need to leave the event loop.
        try:
            event = self._client.construct_event(
                payload=payload, sig_header=signature, secret=settings.STRIPE_WEBHOOK_SECRET or ""
            )
        except (ValueError, stripe.SignatureVerificationError) as error:
            raise WebhookSignatureError("Invalid Stripe webhook") from error
        return _webhook_event(event.to_dict())

    async def get_one_off_price(self, key: str) -> Optional[OneOffPrice]:
        prices = await self._call(
            "look up the Top-up price",
            lambda: self._client.v1.prices.list({"active": True, "lookup_keys": [key], "limit": 1}),
        )
        return next((price for p in prices.data if (price := _one_off_price(p.to_dict()))), None)

    async def create_top_up_checkout(
        self, *, customer_id: str, price_id: str, user_id: str
    ) -> CheckoutSession:
        params: CheckoutSessionCreateParams = {
            "mode": "payment",
            "customer": customer_id,
            "client_reference_id": user_id,
            "line_items": [{"price": price_id, "quantity": 1}],
            "metadata": _TOP_UP_METADATA,
            "success_url": settings.stripe_top_up_success_url(),
            "cancel_url": settings.billing_page_url(),
            "automatic_tax": {"enabled": True},
            "tax_id_collection": {"enabled": True},
            "customer_update": {"address": "auto", "name": "auto"},
            "managed_payments": {"enabled": False},
        }
        session = await self._call(
            "create a Top-up Checkout", lambda: self._client.v1.checkout.sessions.create(params)
        )
        if not session.url:
            raise BillingProviderError(f"Stripe Checkout {session.id} has no URL")
        return CheckoutSession(id=session.id, url=session.url)

    async def list_top_ups(self, *, customer_id: str) -> list[TopUpPurchase]:
        # Checkouts expanded to their charge carry refunds and disputes: one call per 100,
        # where listing charges would take another call per charge to find its Checkout.
        def list_all() -> list[dict[str, Any]]:
            sessions = self._client.v1.checkout.sessions.list(
                {
                    "customer": customer_id,
                    "status": "complete",
                    "expand": ["data.payment_intent.latest_charge"],
                    "limit": 100,
                }
            )
            return [session.to_dict() for session in sessions.auto_paging_iter()]

        sessions = await self._call("list Top-ups", list_all)
        return [purchase for s in sessions if (purchase := _top_up_purchase(s))]

    async def get_charge_customer(self, *, charge_id: str) -> Optional[str]:
        charge = await self._call(
            "look up a charge", lambda: self._client.v1.charges.retrieve(charge_id)
        )
        return _customer_id(charge.to_dict().get("customer"))


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


@dataclass(frozen=True)
class TopUpCheckoutCall:
    customer_id: str
    price_id: str
    user_id: str


@dataclass
class FakeBillingGateway:
    """
    A billing provider in memory that records every call and raises `BillingProviderError`
    from any method in `fail_on`. It verifies only payloads signed with its own secret.
    """

    webhook_secret: str = "whsec_fake"
    fail_on: set[str] = field(default_factory=set)
    checkout_url: str = "https://checkout.test/session"
    portal_url: str = "https://billing.test/portal"
    plans: list[Plan] = field(default_factory=list)
    # The provider's "now", for what ending a Trial stamps on the Subscription.
    clock: Clock = system_clock
    # Whether the charge that ends a Trial fails, leaving the Subscription past due.
    first_charge_fails: bool = False
    # Where the charge that ends a Trial waits for the User to authenticate it, past due till then.
    first_charge_authentication_url: Optional[str] = None

    customers_created: list[CustomerCall] = field(default_factory=list)
    checkouts: list[CheckoutCall] = field(default_factory=list)
    portals: list[str] = field(default_factory=list)
    plan_lookups: list[list[str]] = field(default_factory=list)
    expired_checkouts: list[str] = field(default_factory=list)
    cancelled_subscriptions: list[str] = field(default_factory=list)
    unsettled_invoice_customers: set[str] = field(default_factory=set)
    prices: list[OneOffPrice] = field(default_factory=list)
    top_up_checkouts: list[TopUpCheckoutCall] = field(default_factory=list)
    ended_trials: list[str] = field(default_factory=list)
    deferrals: list[tuple[str, datetime, str]] = field(default_factory=list)

    _open_checkouts: dict[str, str] = field(default_factory=dict, init=False)
    _payment_checkouts: dict[str, tuple[str, str]] = field(default_factory=dict, init=False)
    _subscriptions: dict[str, dict[str, SubscriptionState]] = field(
        default_factory=dict, init=False
    )
    _customers_by_idempotency_key: dict[str, str] = field(default_factory=dict, init=False)
    _top_ups: dict[str, dict[str, TopUpPurchase]] = field(default_factory=dict, init=False)

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
        result = self._customers_by_idempotency_key.setdefault(
            idempotency_key, f"cus_fake_{len(self._customers_by_idempotency_key) + 1}"
        )
        self._maybe_fail("after_create_customer")
        return result

    async def find_user_customers(self, *, user_id: str) -> list[str]:
        self._maybe_fail("find_user_customers")
        return list(
            dict.fromkeys(
                self._customers_by_idempotency_key[c.idempotency_key]
                for c in self.customers_created
                if c.user_id == user_id
            )
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

    paid_signup_setups: dict[str, PaidSignupSetup] = field(default_factory=dict)
    paid_signups_created: list[str] = field(default_factory=list)

    async def create_paid_signup_setup(
        self,
        *,
        customer_id: str,
        user_id: str,
        operation_id: str,
        currency: str,
        expires_at: datetime,
    ) -> PaidSignupSetup:
        self._maybe_fail("create_paid_signup_setup")
        previous = [s for s in self.paid_signup_setups.values() if s.operation_id == operation_id]
        if previous:
            return previous[0]
        setup = PaidSignupSetup(
            id=f"cs_setup_{len(self.paid_signup_setups) + 1}",
            customer_id=customer_id,
            operation_id=operation_id,
            status="open",
            url=self.checkout_url,
        )
        self.paid_signup_setups[setup.id] = setup
        self._maybe_fail("after_create_paid_signup_setup")
        return setup

    async def list_paid_signup_setups(self, *, customer_id: str) -> list[PaidSignupSetup]:
        self._maybe_fail("list_paid_signup_setups")
        return [s for s in self.paid_signup_setups.values() if s.customer_id == customer_id]

    async def expire_paid_signup_setup(self, *, session_id: str) -> None:
        self._maybe_fail("expire_paid_signup_setup")
        self.paid_signup_setups[session_id] = replace(
            self.paid_signup_setups[session_id], status="expired", url=None
        )

    def complete_paid_signup_setup(self, session_id: str) -> None:
        setup = self.paid_signup_setups[session_id]
        self.paid_signup_setups[session_id] = replace(
            setup,
            status="complete",
            url=None,
            setup_status="succeeded",
            payment_method_id=f"pm_{session_id}",
            setup_customer_id=setup.customer_id,
            payment_method_customer_id=setup.customer_id,
            usage="off_session",
        )

    async def create_paid_signup(
        self,
        *,
        customer_id: str,
        price_id: str,
        payment_method_id: str,
        operation_id: str,
        first_payment_at: datetime,
    ) -> None:
        self._maybe_fail("create_paid_signup")
        if first_payment_at <= self.clock():
            raise DeferralRefused("The accepted date has passed")
        if any(
            s.paid_signup_operation == operation_id
            for s in self._subscriptions.get(customer_id, {}).values()
        ):
            return
        plan = next(p for p in self.plans if p.price_id == price_id)
        self.paid_signups_created.append(operation_id)
        self.set_subscription(
            customer_id,
            SubscriptionState(
                id=f"sub_signup_{len(self.paid_signups_created)}",
                status="trialing",
                price_id=price_id,
                plan_key=plan.key,
                current_period_start=self.clock(),
                current_period_end=first_payment_at,
                created_at=self.clock(),
                trial_start=self.clock(),
                trial_end=first_payment_at,
                billing_cycle_anchor=first_payment_at,
                item_id=f"si_{operation_id}",
                item_count=1,
                interval=plan.interval,
                interval_count=plan.interval_count,
                billing_mode="classic",
                latest_invoice_status="paid",
                paid_signup_operation=operation_id,
            ),
        )
        self._maybe_fail("after_create_paid_signup")

    async def has_open_subscription_checkout(self, *, customer_id: str) -> bool:
        self._maybe_fail("has_open_subscription_checkout")
        return customer_id in self._open_checkouts.values()

    async def has_pending_checkout(self, *, customer_id: str) -> bool:
        self._maybe_fail("has_pending_checkout")
        return (
            any(
                s.customer_id == customer_id and s.status == "open"
                for s in self.paid_signup_setups.values()
            )
            or customer_id in self._open_checkouts.values()
            or any(customer == customer_id for customer, _ in self._payment_checkouts.values())
        )

    async def expire_open_checkouts(self, *, customer_id: str) -> list[str]:
        self._maybe_fail("expire_open_checkouts")
        expired = [s for s, c in self._open_checkouts.items() if c == customer_id]
        expired.extend(
            s
            for s, (c, status) in self._payment_checkouts.items()
            if c == customer_id and status == "open"
        )
        for session_id in expired:
            self._open_checkouts.pop(session_id, None)
            self._payment_checkouts.pop(session_id, None)
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

    async def has_unsettled_invoices(self, *, customer_id: str) -> bool:
        self._maybe_fail("has_unsettled_invoices")
        return customer_id in self.unsettled_invoice_customers

    async def cancel_subscription(self, *, subscription_id: str) -> None:
        self._maybe_fail("cancel_subscription")
        self.cancelled_subscriptions.append(subscription_id)
        for subscriptions in self._subscriptions.values():
            if subscription := subscriptions.get(subscription_id):
                subscriptions[subscription_id] = replace(subscription, status="canceled")

    async def defer_renewal(
        self, *, subscription_id: str, target: datetime, operation_id: str
    ) -> None:
        self._maybe_fail("defer_renewal")
        if "refuse_deferral" in self.fail_on:
            raise DeferralRefused("The deferral was refused")
        self.deferrals.append((subscription_id, target, operation_id))
        for subscriptions in self._subscriptions.values():
            if subscription := subscriptions.get(subscription_id):
                subscriptions[subscription_id] = replace(
                    subscription,
                    status="trialing",
                    trial_start=self.clock(),
                    trial_end=target,
                    billing_cycle_anchor=target,
                    current_period_end=target,
                    coupon_operation=operation_id,
                    paid_current_period=False,
                )
        self._maybe_fail("after_defer_renewal")

    async def cancel_renewal(self, *, subscription_id: str, ends_at: datetime) -> None:
        self._maybe_fail("cancel_renewal")
        for subscriptions in self._subscriptions.values():
            if subscription := subscriptions.get(subscription_id):
                subscriptions[subscription_id] = replace(subscription, cancel_at=ends_at)

    async def end_trial(self, *, subscription_id: str) -> Optional[str]:
        self._maybe_fail("end_trial")
        charged = not self.first_charge_fails and self.first_charge_authentication_url is None
        now = self.clock()
        for subscriptions in self._subscriptions.values():
            if subscription := subscriptions.get(subscription_id):
                if subscription.status != "trialing":
                    return self.first_charge_authentication_url
                self.ended_trials.append(subscription_id)
                subscriptions[subscription_id] = replace(
                    subscription,
                    status="active" if charged else "past_due",
                    trial_end=now,
                    billing_cycle_anchor=now,
                    current_period_end=months_after(now, 1),
                )
        self._maybe_fail("after_end_trial")
        return self.first_charge_authentication_url

    def signed_event(
        self, *, event_id: str, event_type: str, data_object: dict[str, Any]
    ) -> tuple[bytes, str]:
        """
        A webhook payload and signature header in Stripe's shape and signing scheme,
        so `StripeBillingGateway` verifies it too when given the same secret.
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

    async def get_one_off_price(self, key: str) -> Optional[OneOffPrice]:
        self._maybe_fail("get_one_off_price")
        return next((price for price in self.prices if price.key == key), None)

    async def create_top_up_checkout(
        self, *, customer_id: str, price_id: str, user_id: str
    ) -> CheckoutSession:
        self._maybe_fail("create_top_up_checkout")
        self.top_up_checkouts.append(
            TopUpCheckoutCall(customer_id=customer_id, price_id=price_id, user_id=user_id)
        )
        session_id = f"cs_top_up_fake_{len(self.top_up_checkouts)}"
        self._payment_checkouts[session_id] = (customer_id, "open")
        return CheckoutSession(id=session_id, url=self.checkout_url)

    def set_top_up_payment_pending(self, *, customer_id: str, checkout_session_id: str) -> None:
        self._payment_checkouts[checkout_session_id] = (customer_id, "unpaid")

    def set_top_up_payment_canceled(self, *, checkout_session_id: str) -> None:
        self._payment_checkouts.pop(checkout_session_id, None)

    def set_top_up(self, customer_id: str, purchase: TopUpPurchase) -> None:
        """Make `purchase` what the provider holds now, replacing any for its Checkout."""
        self._top_ups.setdefault(customer_id, {})[purchase.checkout_session_id] = purchase
        self._payment_checkouts.pop(purchase.checkout_session_id, None)

    async def list_top_ups(self, *, customer_id: str) -> list[TopUpPurchase]:
        self._maybe_fail("list_top_ups")
        return list(self._top_ups.get(customer_id, {}).values())

    async def get_charge_customer(self, *, charge_id: str) -> Optional[str]:
        self._maybe_fail("get_charge_customer")
        return next(
            (
                customer_id
                for customer_id, purchases in self._top_ups.items()
                if any(p.charge_id == charge_id for p in purchases.values())
            ),
            None,
        )

    def _sign(self, timestamp: str, payload: bytes) -> str:
        signed = f"{timestamp}.".encode() + payload
        return hmac.new(self.webhook_secret.encode(), signed, hashlib.sha256).hexdigest()


@lru_cache
def get_billing_gateway() -> BillingGateway:
    """FastAPI dependency for the `BillingGateway` port."""
    return StripeBillingGateway()
