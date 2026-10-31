"""
Allowances (ADR 0017): the limits that apply to a User at a moment, the Allowance period that
holds the moment, and the refusal when an action needs more than is left. Billing knows no usage:
each area above it counts its own against these.
"""

import calendar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pumpkit.billing.models import AllowanceCount, Subscription
from pumpkit.core.config import settings
from pumpkit.core.errors import ConflictError
from pumpkit.core.time import as_utc

# Where the User sees their Allowance and finds the way out.
SETTINGS_PAGE = "/settings"

# What a User at a limit can do before the period resets.
WayOut = Literal["top_up", "subscribe_now", "update_payment"]


@dataclass(frozen=True)
class AllowancePeriod:
    """The stretch `[start, end)` one Allowance covers; a Trial is one period on its own."""

    start: datetime
    end: datetime
    trial: bool


@dataclass(frozen=True)
class Allowance:
    """
    The limits that apply to a User at a moment, in the period holding it, and the way out they
    have now. A limit of None is no cap.
    """

    period: AllowancePeriod
    generations: Optional[int]
    x_posts: Optional[int]
    # Of the X posts, how many may contain a link.
    link_x_posts: Optional[int]
    way_out: Optional[WayOut]


def trial_share(cap: Optional[int]) -> Optional[int]:
    """A Trial gets a quarter of each cap, so changing a cap keeps the Trial in proportion."""
    return None if cap is None else cap // 4


@dataclass(frozen=True)
class Limits:
    """What one Allowance period allows: None is no cap."""

    generations: Optional[int]
    x_posts: Optional[int]
    link_x_posts: Optional[int]


def limits(*, trial: bool) -> Limits:
    """The Instance's limits for a paid period, or for a Trial."""

    def share(cap: Optional[int]) -> Optional[int]:
        return trial_share(cap) if trial else cap

    return Limits(
        generations=share(settings.GENERATIONS_MONTHLY_CAP),
        x_posts=share(settings.X_POSTS_MONTHLY_CAP),
        link_x_posts=share(settings.X_LINK_POSTS_MONTHLY_CAP),
    )


def top_up_pack() -> Limits:
    """A Top-up is half of each cap, so changing a cap keeps it in proportion (ADR 0017)."""

    def half(cap: Optional[int]) -> Optional[int]:
        return None if cap is None else cap // 2

    return Limits(
        generations=half(settings.GENERATIONS_MONTHLY_CAP),
        x_posts=half(settings.X_POSTS_MONTHLY_CAP),
        link_x_posts=half(settings.X_LINK_POSTS_MONTHLY_CAP),
    )


def sells_top_ups() -> bool:
    """Whether this Instance sells Top-ups: only where it sells Plans and names the Top-up's price."""
    return settings.is_stripe_billing_configured() and bool(settings.BILLING_TOP_UP_KEY)


def months_after(anchor: datetime, months: int) -> datetime:
    """`anchor` moved by whole months, on the anchor's day or the last day of a shorter month."""
    index = anchor.year * 12 + anchor.month - 1 + months
    year, month = divmod(index, 12)
    day = min(anchor.day, calendar.monthrange(year, month + 1)[1])
    return anchor.replace(year=year, month=month + 1, day=day)


def paid_period(anchor: datetime, moment: datetime) -> AllowancePeriod:
    """
    The monthly period holding `moment`: each starts on the anchor's day of the month at its time
    of day, on annual Plans too. Moments past the Subscription's known end fall in the period
    they would if it ran on.
    """
    anchor = as_utc(anchor)
    moment = moment.astimezone(timezone.utc)
    months = (moment.year - anchor.year) * 12 + moment.month - anchor.month
    if months_after(anchor, months) > moment:
        months -= 1
    return AllowancePeriod(
        start=months_after(anchor, months), end=months_after(anchor, months + 1), trial=False
    )


def period_at(subscription: Subscription, moment: datetime) -> AllowancePeriod:
    """The Trial while `moment` is in it, else the paid period from the billing cycle anchor."""
    trial_start, trial_end = subscription.trial_start, subscription.trial_end
    if trial_start is not None and trial_end is not None and moment < as_utc(trial_end):
        return AllowancePeriod(start=as_utc(trial_start), end=as_utc(trial_end), trial=True)
    # A row not synced since the anchor was stored falls back to the start.
    anchor = subscription.billing_cycle_anchor or subscription.stripe_created_at
    return paid_period(anchor, moment)


def way_out_for(subscription: Subscription) -> Optional[WayOut]:
    if subscription.status == "trialing":
        return "subscribe_now"
    if subscription.status == "past_due":
        return "update_payment"
    if may_buy_top_up(subscription):
        return "top_up"
    return None


def may_buy_top_up(subscription: Optional[Subscription]) -> bool:
    """Only a paid-up paid Subscription buys a Top-up: not in a Trial, not behind on payment."""
    return sells_top_ups() and subscription is not None and subscription.status == "active"


def allowance_at(subscription: Subscription, moment: datetime) -> Allowance:
    """The Allowance of a Subscribed User's `subscription` at `moment`."""
    period = period_at(subscription, moment)
    caps = limits(trial=period.trial)
    return Allowance(
        period=period,
        generations=caps.generations,
        x_posts=caps.x_posts,
        link_x_posts=caps.link_x_posts,
        way_out=way_out_for(subscription),
    )


_NOUNS: dict[AllowanceCount, str] = {
    "generations": "generations",
    "x_posts": "X posts",
    "link_x_posts": "X posts with a link",
}


def _day(moment: datetime) -> str:
    return f"{moment.day} {moment:%B}"


class AllowanceUsedUp(ConflictError):
    """
    An action needs more of an Allowance than is left. The body carries what ran out, how many the
    action needs and has left, when the period resets and the way out, for the web app to offer.
    """

    def __init__(
        self, *, ran_out: AllowanceCount, needed: int, left: int, limit: int, allowance: Allowance
    ) -> None:
        period = allowance.period
        noun = _NOUNS[ran_out]
        if needed > 1 and left > 0:
            # Only a Thread needs several at once, and it is refused whole.
            in_trial = " in your trial" if period.trial else ""
            used = f"This thread needs {needed} {noun} and you have {left} left{in_trial}."
        elif period.trial:
            used = f"You've used your trial's {limit} {noun}."
        else:
            used = f"You've used this period's {limit} {noun}."
        if period.trial:
            used = f"{used} Your trial ends on {_day(period.end)}."
        else:
            used = f"{used} They reset on {_day(period.end)}."
        if ran_out == "generations":
            used = f"{used} Failed attempts don't count."
        super().__init__(used, fix_page=SETTINGS_PAGE)
        self.ran_out = ran_out
        self.needed = needed
        self.left = left
        self.resets_at = period.end
        self.way_out = allowance.way_out

    def response_body(self) -> dict[str, Any]:
        return {
            **super().response_body(),
            "code": "ALLOWANCE_USED_UP",
            "ran_out": self.ran_out,
            "needed": self.needed,
            "left": self.left,
            "resets_at": self.resets_at.isoformat().replace("+00:00", "Z"),
            "way_out": self.way_out,
        }


def check_room(
    *, ran_out: AllowanceCount, limit: Optional[int], used: int, needed: int, allowance: Allowance
) -> None:
    """Raise `AllowanceUsedUp` when `needed` more would take `used` past `limit`."""
    if limit is None or used + needed <= limit:
        return
    raise AllowanceUsedUp(
        ran_out=ran_out,
        needed=needed,
        left=max(0, limit - used),
        limit=limit,
        allowance=allowance,
    )
