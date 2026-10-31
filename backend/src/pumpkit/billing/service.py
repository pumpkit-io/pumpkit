"""
Pumpkit's copy of each Subscription and Top-up, synced from the billing provider (ADR 0004),
the Stripe event log that makes webhooks idempotent, and Users' acceptances of the Terms.
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.billing.allowance import (
    Allowance,
    AllowanceUsedUp,
    allowance_at,
    months_after,
    top_up_pack,
)
from pumpkit.billing.gateway import BillingGateway
from pumpkit.billing.models import (
    AllowanceCount,
    StripeEvent,
    Subscription,
    TermsAcceptance,
    TopUp,
    TopUpCharge,
)
from pumpkit.billing.subscription_status import SubscriptionStatus
from pumpkit.billing.top_ups import TopUpBalance, allocate, shortfall
from pumpkit.core.config import settings
from pumpkit.core.time import as_utc

# How long a Top-up lasts from its purchase.
TOP_UP_MONTHS = 12

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
    A User may subscribe only with no Running Subscription; only one who never had any gets a Trial.
    A Trial Checkout starts trialing, never `incomplete`, so cancelling `incomplete` costs no Trial.
    Reads only Pumpkit's copy: sync the customer first to match the provider.
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
    """Whether the User ever had a Subscription in any status, which uses up their Trial."""
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
    Ordered by Stripe's creation time, not the row's: rows synced in one transaction share it.
    Ties go to the greater provider ID so the answer is stable.
    """
    result = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id, Subscription.status.in_(statuses))
        .order_by(Subscription.stripe_created_at.desc(), Subscription.stripe_subscription_id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def sells_plans() -> bool:
    """Whether this Instance sells Plans: only with the Stripe settings group (ADR 0011)."""
    return settings.is_stripe_billing_configured()


def requires_terms_acceptance() -> bool:
    """Whether a checkout must accept the Terms: only with Plans and Operator details (ADR 0011)."""
    return sells_plans() and settings.is_operator_configured()


async def has_access(db: AsyncSession, *, user_id: str) -> bool:
    """Whether a User may use Pumpkit: always where no Plans are sold, else only when Subscribed."""
    if not sells_plans():
        return True
    return is_subscribed(await get_user_subscription(db, user_id=user_id))


async def get_allowance(db: AsyncSession, *, user_id: str, moment: datetime) -> Optional[Allowance]:
    """
    The limits that apply to the User at `moment`: None where the Instance sells no Plans or the
    User isn't Subscribed, who may then do nothing an Allowance counts.
    """
    if not sells_plans():
        return None
    subscription = await get_user_subscription(db, user_id=user_id)
    if subscription is None or not is_subscribed(subscription):
        return None
    return allowance_at(subscription, moment)


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
    query = select(Subscription).where(
        Subscription.stripe_subscription_id == stripe_subscription_id
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def sync_customer(
    db: AsyncSession, gateway: BillingGateway, *, user_id: str, customer_id: str
) -> None:
    """
    Make Pumpkit's copy of the customer's Subscriptions match the provider's now (ADR 0004).
    Never overwrites an Ended one: a guard against bugs, not event ordering. Flushes, never commits.
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
        subscription.trial_start = state.trial_start
        subscription.trial_end = state.trial_end
        subscription.billing_cycle_anchor = state.billing_cycle_anchor
    await db.flush()


async def record_terms_acceptance(
    db: AsyncSession,
    *,
    user_id: str,
    terms_version: str,
    accepted_terms: bool,
    requested_immediate_start: bool,
    approved_specific_clauses: bool,
) -> TermsAcceptance:
    """Record that the User accepted `terms_version` with these boxes ticked. Flushes, never commits."""
    acceptance = TermsAcceptance(
        user_id=user_id,
        terms_version=terms_version,
        accepted_terms=accepted_terms,
        requested_immediate_start=requested_immediate_start,
        approved_specific_clauses=approved_specific_clauses,
    )
    db.add(acceptance)
    await db.flush()
    return acceptance


async def try_record_event(
    db: AsyncSession,
    *,
    event_id: str,
    event_type: str,
) -> bool:
    """
    Record `event_id`, returning True only the first time it is seen.

    The existence check keeps the common path cheap; the savepoint catches two
    concurrent handlers that both pass it and race on the insert.
    """
    existing = await db.execute(select(StripeEvent.id).where(StripeEvent.id == event_id))
    if existing.scalar_one_or_none() is not None:
        return False

    try:
        async with db.begin_nested():
            db.add(StripeEvent(id=event_id, type=event_type))
            await db.flush()
    except IntegrityError:
        return False
    return True


async def top_up_balances(
    db: AsyncSession,
    *,
    user_id: str,
    moment: datetime,
    giving_back: Collection[str] = (),
) -> list[TopUpBalance]:
    """
    What each of the User's Top-ups unexpired at `moment` has left, first to expire first, with
    the charges of the Scheduled posts `giving_back` given back.
    """
    top_ups = list(
        (
            await db.execute(
                select(TopUp)
                .where(
                    TopUp.user_id == user_id,
                    TopUp.removed.is_(False),
                    TopUp.expires_at > moment,
                )
                .order_by(TopUp.expires_at, TopUp.id)
            )
        ).scalars()
    )
    if not top_ups:
        return []
    charged: dict[tuple[str, str], int] = {
        (top_up_id, count): quantity
        for top_up_id, count, quantity in (
            await db.execute(
                select(TopUpCharge.top_up_id, TopUpCharge.count, func.sum(TopUpCharge.quantity))
                .where(
                    TopUpCharge.top_up_id.in_([t.id for t in top_ups]),
                    or_(
                        TopUpCharge.scheduled_post_id.is_(None),
                        TopUpCharge.scheduled_post_id.not_in(giving_back),
                    ),
                )
                .group_by(TopUpCharge.top_up_id, TopUpCharge.count)
            )
        ).tuples()
    }
    return [
        TopUpBalance(
            id=t.id,
            expires_at=as_utc(t.expires_at),
            generations=_pack_left(t.generations, charged.get((t.id, "generations"), 0)),
            x_posts=_pack_left(t.x_posts, charged.get((t.id, "x_posts"), 0)),
            link_x_posts=_pack_left(t.link_x_posts, charged.get((t.id, "link_x_posts"), 0)),
        )
        for t in top_ups
    ]


def _pack_left(pack: Optional[int], charged: int) -> Optional[int]:
    return None if pack is None else pack - charged


async def check_room_with_top_ups(
    db: AsyncSession,
    *,
    user_id: str,
    allowance: Allowance,
    count: AllowanceCount,
    used: int,
    needed: int,
    moment: datetime,
) -> None:
    """
    Raise `AllowanceUsedUp` unless the Allowance, with `used` gone, and the User's Top-ups
    unexpired at `moment` together have room for `needed` more of `count`.
    """
    limit: Optional[int] = getattr(allowance, count)
    short = shortfall(limit=limit, used=used, needed=needed)
    if limit is None or short == 0:
        return
    in_top_ups = sum(
        b.left(count) for b in await top_up_balances(db, user_id=user_id, moment=moment)
    )
    if in_top_ups >= short:
        return
    raise AllowanceUsedUp(
        ran_out=count,
        needed=needed,
        left=max(0, limit - used) + in_top_ups,
        limit=limit,
        allowance=allowance,
    )


async def charge_shortfall(
    db: AsyncSession,
    *,
    user_id: str,
    allowance: Allowance,
    count: AllowanceCount,
    used: int,
    needed: int,
    moment: datetime,
    version_attempt_id: str,
) -> int:
    """
    Charge what the Allowance, with `used` gone, can't cover of `needed` to the Top-ups unexpired
    at `moment`, first to expire first, and return how many were charged. What they can't cover
    either stays on the Allowance, over its limit. Flushes.
    """
    short = shortfall(limit=getattr(allowance, count), used=used, needed=needed)
    if short == 0:
        return 0
    balances = await top_up_balances(db, user_id=user_id, moment=moment)
    charges = allocate(balances, count=count, quantity=short)
    for top_up_id, quantity in charges:
        db.add(
            TopUpCharge(
                top_up_id=top_up_id,
                count=count,
                quantity=quantity,
                version_attempt_id=version_attempt_id,
            )
        )
    await db.flush()
    return sum(quantity for _, quantity in charges)


async def record_charges(
    db: AsyncSession,
    *,
    scheduled_post_id: str,
    count: AllowanceCount,
    charges: list[tuple[str, int]],
) -> None:
    """Record what the Scheduled post takes from each Top-up, as (Top-up, quantity). Flushes."""
    db.add_all(
        TopUpCharge(
            top_up_id=top_up_id, count=count, quantity=quantity, scheduled_post_id=scheduled_post_id
        )
        for top_up_id, quantity in charges
    )
    await db.flush()


async def give_back_charges(
    db: AsyncSession, *, scheduled_post_id: str, keeping_removed: bool = False
) -> None:
    """
    Delete what the Scheduled post took from Top-ups, so they have it again. With
    `keeping_removed`, what it took from a removed Top-up stays: it was paid for. Flushes.
    """
    query = delete(TopUpCharge).where(TopUpCharge.scheduled_post_id == scheduled_post_id)
    if keeping_removed:
        query = query.where(
            TopUpCharge.top_up_id.in_(select(TopUp.id).where(TopUp.removed.is_(False)))
        )
    await db.execute(query.execution_options(synchronize_session=False))
    await db.flush()


async def charges_on_removed(
    db: AsyncSession, *, scheduled_post_id: str
) -> dict[AllowanceCount, int]:
    """What the Scheduled post took from Top-ups since removed, by count."""
    result = await db.execute(
        select(TopUpCharge.count, func.sum(TopUpCharge.quantity))
        .join(TopUp, TopUpCharge.top_up_id == TopUp.id)
        .where(TopUpCharge.scheduled_post_id == scheduled_post_id, TopUp.removed.is_(True))
        .group_by(TopUpCharge.count)
    )
    return {count: quantity for count, quantity in result.tuples()}


async def trim_charges_on_removed(
    db: AsyncSession, *, scheduled_post_id: str, count: AllowanceCount, keep: int
) -> None:
    """Cut what the Scheduled post took of `count` from removed Top-ups down to `keep`. Flushes."""
    charges = (
        await db.execute(
            select(TopUpCharge)
            .join(TopUp, TopUpCharge.top_up_id == TopUp.id)
            .where(
                TopUpCharge.scheduled_post_id == scheduled_post_id,
                TopUpCharge.count == count,
                TopUp.removed.is_(True),
            )
            .order_by(TopUpCharge.id)
        )
    ).scalars()
    for charge in charges:
        kept = min(charge.quantity, keep)
        keep -= kept
        if kept == 0:
            await db.delete(charge)
        else:
            charge.quantity = kept
    await db.flush()


async def sync_top_ups(
    db: AsyncSession, gateway: BillingGateway, *, user_id: str, customer_id: str
) -> list[TopUp]:
    """
    Make Pumpkit's copy of the customer's Top-ups match the provider's now: add the paid ones it
    lacks, and remove refunded or disputed ones, for good. Returns the added ones. Flushes.
    """
    added: list[TopUp] = []
    for purchase in await gateway.list_top_ups(customer_id=customer_id):
        top_up = (
            await db.execute(
                select(TopUp).where(
                    TopUp.stripe_checkout_session_id == purchase.checkout_session_id
                )
            )
        ).scalar_one_or_none()
        if top_up is not None:
            top_up.removed = top_up.removed or purchase.reversed
            continue
        pack = top_up_pack()
        top_up = TopUp(
            user_id=user_id,
            stripe_checkout_session_id=purchase.checkout_session_id,
            generations=pack.generations,
            x_posts=pack.x_posts,
            link_x_posts=pack.link_x_posts,
            purchased_at=purchase.paid_at,
            expires_at=months_after(purchase.paid_at, TOP_UP_MONTHS),
            removed=purchase.reversed,
        )
        db.add(top_up)
        added.append(top_up)
    await db.flush()
    return added
