from datetime import datetime
from typing import TYPE_CHECKING, Literal, Optional, get_args

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy import Enum as PgEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pumpkit.billing.subscription_status import SubscriptionStatus
from pumpkit.core.db.base import Base
from pumpkit.core.ids import ulid_with_prefix

if TYPE_CHECKING:
    from pumpkit.auth.models import User

# Unique and primary key columns are indexed automatically, so they don't set index=True.

# What an Allowance, and a Top-up, counts.
AllowanceCount = Literal["generations", "x_posts", "link_x_posts"]


class Subscription(Base):
    """
    Pumpkit's copy of a Subscription as Stripe holds it, so reads don't call
    Stripe. Synced from Stripe whenever a webhook nudges (ADR 0004).
    """

    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("subscription")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    stripe_subscription_id: Mapped[str] = mapped_column(String, unique=True)
    stripe_customer_id: Mapped[str] = mapped_column(String, index=True)
    stripe_price_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    # The price's lookup key; None when the price has none.
    plan_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[SubscriptionStatus] = mapped_column(
        PgEnum(*get_args(SubscriptionStatus), name="subscription_status_enum"), index=True
    )
    current_period_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    # When Stripe created the Subscription: the order between a User's
    # Subscriptions, since rows synced in one transaction share `created_at`.
    stripe_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # What Allowance periods hang on; None on a row not synced since they were added.
    trial_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    trial_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # When paid periods start: the Trial's end after a Trial, else the start.
    billing_cycle_anchor: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship()


class StripeEvent(Base):
    """
    Idempotency log: the insert succeeds only for an unseen ``event.id``,
    so the webhook dispatcher skips replays.
    """

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TermsAcceptance(Base):
    """
    A User's acceptance of one Terms version before a checkout (ADR 0010), as evidence of
    what they agreed to and when. One row per checkout request, kept even if the checkout fails.
    """

    __tablename__ = "terms_acceptances"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("terms_acceptance")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    terms_version: Mapped[str] = mapped_column(String)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    accepted_terms: Mapped[bool] = mapped_column(Boolean)
    requested_immediate_start: Mapped[bool] = mapped_column(Boolean)
    approved_specific_clauses: Mapped[bool] = mapped_column(Boolean)


class TopUp(Base):
    """
    A paid Top-up (ADR 0017), synced from its Stripe Checkout. What is left of it is its pack less
    its charges; a refund or dispute removes it.
    """

    __tablename__ = "top_ups"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("top_up")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    stripe_checkout_session_id: Mapped[str] = mapped_column(String, unique=True)
    # The pack, half of each cap when it was bought; None for a count that had no cap, which it
    # never adds to, unlike a 0 from a small cap rounded down.
    generations: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    x_posts: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    link_x_posts: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    removed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TopUpCharge(Base):
    """
    What one Version attempt or Scheduled post took from a Top-up. Their tables belong to areas
    above billing, so only the foreign keys name them; deleting either gives the charge back,
    except a deleted Scheduled post's live Parts, whose charges stay with neither named.
    """

    __tablename__ = "top_up_charges"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("top_up_charge")
    )
    top_up_id: Mapped[str] = mapped_column(ForeignKey("top_ups.id", ondelete="CASCADE"), index=True)
    count: Mapped[AllowanceCount] = mapped_column(
        PgEnum(*get_args(AllowanceCount), name="allowance_count_enum")
    )
    quantity: Mapped[int] = mapped_column(Integer)
    version_attempt_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("version_attempts.id", ondelete="CASCADE"), index=True, nullable=True
    )
    scheduled_post_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("scheduled_posts.id", ondelete="CASCADE"), index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
