"""Pumpkit's copy of each Subscription, synced from the billing provider (ADR 0004)."""

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.billing_gateway import BillingGateway
from app.core.config import settings
from app.core.subscription_status import SubscriptionStatus
from app.db.models import Subscription

# An Ended Subscription can never run again.
_ENDED_STATUSES: set[SubscriptionStatus] = {"canceled", "incomplete_expired"}
# A Running Subscription has started and not Ended. `incomplete` is neither.
_RUNNING_STATUSES: set[SubscriptionStatus] = {
    "trialing",
    "active",
    "past_due",
    "unpaid",
    "paused",
}
_INCOMPLETE_STATUSES: set[SubscriptionStatus] = {"incomplete"}
# A Subscribed User's Subscription grants access to Pumpkit.
_SUBSCRIBED_STATUSES: set[SubscriptionStatus] = {"trialing", "active", "past_due"}


@dataclass(frozen=True)
class SubscriptionOffer:
    """
    Whether a User may subscribe, and the Trial a Checkout for them starts with
    (None when they get no Trial, and always None when they may not subscribe).
    """

    may_subscribe: bool
    trial_days: Optional[int]


async def get_subscription_offer(db: AsyncSession, *, user_id: str) -> SubscriptionOffer:
    """
    A User may subscribe only when they have no Running Subscription. The Trial
    is the configured length for a User who has never had any Subscription, in
    any status, and none when Trials are off. A Checkout with a Trial starts its
    Subscription as trialing, never `incomplete`, so cancelling `incomplete`
    Subscriptions can't cost a User their Trial. Reads only Pumpkit's copy:
    sync the customer first for an answer that matches the provider.
    """
    if await _newest_subscription(db, user_id=user_id, statuses=_RUNNING_STATUSES):
        return SubscriptionOffer(may_subscribe=False, trial_days=None)
    days = settings.BILLING_TRIAL_PERIOD_DAYS
    if days == 0 or await has_had_subscription(db, user_id=user_id):
        # A zero length turns Trials off; Stripe rejects a zero-day Trial.
        return SubscriptionOffer(may_subscribe=True, trial_days=None)
    return SubscriptionOffer(may_subscribe=True, trial_days=days)


async def list_incomplete_subscriptions(db: AsyncSession, *, user_id: str) -> list[Subscription]:
    """The User's `incomplete` Subscriptions: started, but their first payment is still pending."""
    result = await db.execute(
        select(Subscription).where(
            Subscription.user_id == user_id, Subscription.status.in_(_INCOMPLETE_STATUSES)
        )
    )
    return list(result.scalars())


async def has_had_subscription(db: AsyncSession, *, user_id: str) -> bool:
    """
    Whether the User has ever had a Subscription, in any status. Only such a
    User has used up their Trial.
    """
    result = await db.execute(select(exists().where(Subscription.user_id == user_id)))
    return bool(result.scalar())


async def get_user_subscription(db: AsyncSession, *, user_id: str) -> Optional[Subscription]:
    """
    The User's Subscription: their Running one, else their newest `incomplete`
    one, else None. Never an Ended one. Reads only Pumpkit's copy.
    """
    return await _newest_subscription(
        db, user_id=user_id, statuses=_RUNNING_STATUSES
    ) or await _newest_subscription(db, user_id=user_id, statuses=_INCOMPLETE_STATUSES)


async def _newest_subscription(
    db: AsyncSession, *, user_id: str, statuses: set[SubscriptionStatus]
) -> Optional[Subscription]:
    """
    The User's Subscription in one of `statuses` that Stripe created last, or
    None. Ordered by Stripe's creation time, not the row's: rows synced in one
    transaction share their write time. Ties go to the greater provider ID, so
    the answer is stable.
    """
    result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id, Subscription.status.in_(statuses))
        .order_by(Subscription.stripe_created_at.desc(), Subscription.stripe_subscription_id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def is_subscribed(subscription: Optional[Subscription]) -> bool:
    """
    Whether a User holding `subscription` is Subscribed: it is in its Trial,
    paid up, or behind on payment while the provider still retries the charge.
    """
    return subscription is not None and subscription.status in _SUBSCRIBED_STATUSES


async def get_subscription_by_stripe_id(
    db: AsyncSession,
    stripe_subscription_id: str,
) -> Optional[Subscription]:
    """
    Fetch a local subscription row by its Stripe subscription id.
    """
    query = select(Subscription).where(
        Subscription.stripe_subscription_id == stripe_subscription_id
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def sync_customer(
    db: AsyncSession, gateway: BillingGateway, *, user_id: str, customer_id: str
) -> None:
    """
    Make Pumpkit's copy of the customer's Subscriptions match what the billing
    provider holds now (ADR 0004), upserting each by its provider ID. An Ended
    Subscription is never overwritten: that guards against bugs, it doesn't
    order events. A provider failure raises `BillingProviderError`. Flushes,
    never commits: the caller owns the transaction.
    """
    for state in await gateway.list_subscriptions(customer_id=customer_id):
        subscription = await get_subscription_by_stripe_id(db, state.id)
        if subscription is None:
            subscription = Subscription(user_id=user_id, stripe_subscription_id=state.id)
            db.add(subscription)
        elif subscription.status in _ENDED_STATUSES:
            continue
        subscription.stripe_customer_id = customer_id
        subscription.stripe_price_id = state.price_id
        subscription.plan_key = state.plan_key
        subscription.status = state.status
        subscription.current_period_end = state.current_period_end
        subscription.cancel_at_period_end = state.cancel_at_period_end
        subscription.stripe_created_at = state.created_at
    await db.flush()
