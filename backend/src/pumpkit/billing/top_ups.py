"""
Spending Top-ups (ADR 0017): only what the Allowance can't cover, from the unexpired Top-up that
expires first, then the next. The same rules serve every count: Generations, X posts, link posts.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from pumpkit.billing.models import AllowanceCount


@dataclass(frozen=True)
class TopUpBalance:
    """What one unexpired, unremoved Top-up has left of each count."""

    id: str
    expires_at: datetime
    generations: int
    x_posts: int
    link_x_posts: int

    def left(self, count: AllowanceCount) -> int:
        return max(0, getattr(self, count))

    def has_left(self) -> bool:
        return any(self.left(count) for count in ("generations", "x_posts", "link_x_posts"))


def shortfall(*, limit: Optional[int], used: int, needed: int) -> int:
    """How many of `needed` the Allowance can't cover with `used` of `limit` gone."""
    if limit is None:
        return 0
    return min(needed, max(0, used + needed - limit))


def allocate(
    balances: list[TopUpBalance], *, count: AllowanceCount, quantity: int
) -> list[tuple[str, int]]:
    """
    `quantity` of `count` split over the Top-ups, first to expire first, as (Top-up, quantity).
    What they can't cover together is left out.
    """
    charges: list[tuple[str, int]] = []
    for balance in sorted(balances, key=lambda b: (b.expires_at, b.id)):
        if quantity == 0:
            break
        taken = min(quantity, balance.left(count))
        if taken:
            charges.append((balance.id, taken))
            quantity -= taken
    return charges
