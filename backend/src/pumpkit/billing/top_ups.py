"""
Spending Top-ups (ADR 0017): only what the Allowance can't cover, from the unexpired Top-up that
expires first, then the next. The same rules serve every count: Generations, X posts, link posts.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional

from pumpkit.billing.models import ALLOWANCE_COUNTS, AllowanceCount


@dataclass(frozen=True)
class TopUpBalance:
    """
    What one unexpired, unremoved Top-up has left of each count; None for a count that had no cap
    when it was bought.
    """

    id: str
    purchased_at: datetime
    expires_at: datetime
    generations: Optional[int]
    x_posts: Optional[int]
    link_x_posts: Optional[int]

    def left(self, count: AllowanceCount) -> int:
        return max(0, getattr(self, count) or 0)

    def left_or_none(self, count: AllowanceCount) -> Optional[int]:
        """What `left` says, or None for a count the Top-up has no number for."""
        return None if getattr(self, count) is None else self.left(count)

    def has_left(self) -> bool:
        return any(self.left(count) for count in ALLOWANCE_COUNTS)


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


@dataclass(frozen=True)
class Need:
    """What one action needs of a count, at the moment it counts."""

    moment: datetime
    quantity: int


@dataclass(frozen=True)
class Covered:
    """How one `Need` is paid for: its Top-up charges, and what nothing covers, over the limit."""

    charges: list[tuple[str, int]]
    uncovered: int


def cover_in_order(
    balances: list[TopUpBalance],
    *,
    count: AllowanceCount,
    limit: Optional[int],
    used: int,
    needs: list[Need],
) -> tuple[list[Covered], list[TopUpBalance]]:
    """
    Pay for `needs`, in order, from the Allowance with `used` of `limit` gone, then each from the
    Top-ups already bought and unexpired at its moment, and return how each is paid and what the Top-ups have left.
    What nothing covers stays on the Allowance, over its limit.
    """
    left = list(balances)
    covered: list[Covered] = []
    for need in needs:
        short = shortfall(limit=limit, used=used, needed=need.quantity)
        charges = allocate(
            [b for b in left if b.purchased_at <= need.moment < b.expires_at],
            count=count,
            quantity=short,
        )
        taken = dict(charges)
        left = [
            replace(b, **{count: b.left(count) - taken[b.id]}) if b.id in taken else b for b in left
        ]
        charged = sum(taken.values())
        used += need.quantity - charged
        covered.append(Covered(charges=charges, uncovered=short - charged))
    return covered, left
