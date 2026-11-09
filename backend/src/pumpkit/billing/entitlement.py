from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pumpkit.billing.allowance import (
    Allowance,
    Limits,
    allowance_at,
    may_buy_top_up,
    paid_period,
    sells_top_ups,
)
from pumpkit.billing.free_access import FreeAccessCoverage
from pumpkit.billing.models import Subscription
from pumpkit.core.time import as_utc, system_clock


@dataclass(frozen=True)
class Entitlement:
    subscription: Optional[Subscription]
    plans_sold: bool
    free_access: Optional[FreeAccessCoverage] = None
    now: datetime = field(default_factory=system_clock)

    @property
    def subscribed(self) -> bool:
        return (
            (
                self.free_access is not None
                and as_utc(self.free_access.starts_at)
                <= self.now
                < as_utc(self.free_access.ends_at)
            )
            or self.subscription is not None
            and self.subscription.status
            in {
                "trialing",
                "active",
                "past_due",
            }
        )

    @property
    def has_access(self) -> bool:
        return not self.plans_sold or self.subscribed

    @property
    def may_buy_top_up(self) -> bool:
        return self.plans_sold and (
            sells_top_ups()
            and self.free_access is not None
            and as_utc(self.free_access.starts_at) <= self.now < as_utc(self.free_access.ends_at)
            or may_buy_top_up(self.subscription)
        )

    def allowance_at(self, moment: datetime) -> Optional[Allowance]:
        if (
            self.plans_sold
            and self.free_access is not None
            and moment >= as_utc(self.free_access.starts_at)
            and (moment < as_utc(self.free_access.ends_at) or self.subscription is None)
        ):
            return Allowance(
                period=paid_period(self.free_access.starts_at, moment),
                limits=Limits(**self.free_access.grant_at(moment).allowance),
                way_out="top_up" if self.may_buy_top_up else None,
                ends_at=as_utc(self.free_access.ends_at),
            )
        if not self.plans_sold or not self.subscribed or self.subscription is None:
            return None
        return allowance_at(self.subscription, moment)
