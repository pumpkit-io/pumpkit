from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from pumpkit.billing.allowance import Allowance, allowance_at, may_buy_top_up
from pumpkit.billing.models import Subscription


@dataclass(frozen=True)
class Entitlement:
    subscription: Optional[Subscription]
    plans_sold: bool

    @property
    def subscribed(self) -> bool:
        return self.subscription is not None and self.subscription.status in {
            "trialing",
            "active",
            "past_due",
        }

    @property
    def has_access(self) -> bool:
        return not self.plans_sold or self.subscribed

    @property
    def may_buy_top_up(self) -> bool:
        return may_buy_top_up(self.subscription)

    def allowance_at(self, moment: datetime) -> Optional[Allowance]:
        if not self.plans_sold or not self.subscribed or self.subscription is None:
            return None
        return allowance_at(self.subscription, moment)
