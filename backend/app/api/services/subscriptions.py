"""Pumpkit's copy of each Subscription, synced from the billing provider (ADR 0004)."""

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.billing_gateway import BillingGateway
from app.core.config import settings
from app.db.models import Subscription, SubscriptionStatus

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
    running = await db.execute(
        select(
            exists().where(
                Subscription.user_id == user_id,
                Subscription.status.in_(_RUNNING_STATUSES),
            )
        )
    )
    if running.scalar():
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
            Subscription.user_id == user_id, Subscription.status == "incomplete"
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


async def get_latest_subscription_for_user(
    db: AsyncSession,
    user_id: str,
) -> Optional[Subscription]:
    """
    Return the most recently created Subscription row for a user, if any.
    """
    query = (
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


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
    await db.flush()


def is_subscription_active(subscription: Optional[Subscription]) -> bool:
    """
    Return True if the given subscription is in a state that grants access.
    """
    if subscription is None:
        return False
    if subscription.status in _ENDED_STATUSES:
        return False
    return subscription.status in ("active", "trialing")
