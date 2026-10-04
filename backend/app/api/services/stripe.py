from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Subscription, SubscriptionStatus, User

# Stripe subscription statuses that represent a terminal lifecycle state
_TERMINAL_STATUSES: set[SubscriptionStatus] = {"canceled", "incomplete_expired"}


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


async def get_user_by_stripe_customer_id(
    db: AsyncSession,
    stripe_customer_id: str,
) -> Optional[User]:
    """
    Look up a user by their Stripe customer id.
    """
    query = select(User).where(User.stripe_customer_id == stripe_customer_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def upsert_subscription(
    db: AsyncSession,
    user_id: str,
    stripe_subscription_id: str,
    stripe_customer_id: str,
    stripe_price_id: Optional[str],
    status: SubscriptionStatus,
    current_period_end: Optional[datetime],
    cancel_at_period_end: bool,
) -> None:
    """
    Insert or update the local Subscription replica keyed by the Stripe subscription ID.
    Does not commit: the caller owns the transaction (webhook dispatcher or trial endpoint).
    """
    subscription = await get_subscription_by_stripe_id(
        db=db, stripe_subscription_id=stripe_subscription_id
    )
    if subscription is None:
        subscription = Subscription(
            user_id=user_id,
            stripe_subscription_id=stripe_subscription_id,
        )
        db.add(subscription)
    subscription.stripe_customer_id = stripe_customer_id
    subscription.stripe_price_id = stripe_price_id
    subscription.status = status
    subscription.current_period_end = current_period_end
    subscription.cancel_at_period_end = cancel_at_period_end
    await db.flush()


def is_subscription_active(subscription: Optional[Subscription]) -> bool:
    """
    Return True if the given subscription is in a state that grants access.
    """
    if subscription is None:
        return False
    if subscription.status in _TERMINAL_STATUSES:
        return False
    return subscription.status in ("active", "trialing")
