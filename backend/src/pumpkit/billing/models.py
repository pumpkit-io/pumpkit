from datetime import datetime
from typing import TYPE_CHECKING, Literal, Optional, get_args

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
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
ALLOWANCE_COUNTS: tuple[AllowanceCount, ...] = get_args(AllowanceCount)


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
    # When a cancelled Subscription ends; None while it renews.
    cancel_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
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

    # Saved coverage uses paid_* fields for both paid periods and original introductory Trials.
    preserved_trial: Mapped[Optional[bool]] = mapped_column(Boolean)
    paid_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    paid_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    paid_anchor: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    paid_allowance: Mapped[Optional[dict]] = mapped_column(JSON)

    user: Mapped["User"] = relationship()


class TrialEligibility(Base):
    """Lifetime trial eligibility for X accounts, independent of account and billing records."""

    __tablename__ = "trial_eligibility"

    key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    eligible: Mapped[bool] = mapped_column(Boolean, default=False)


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
    paid_offer: Mapped[Optional[dict]] = mapped_column(JSON)


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
        PgEnum(*ALLOWANCE_COUNTS, name="allowance_count_enum")
    )
    quantity: Mapped[int] = mapped_column(Integer)
    version_attempt_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("version_attempts.id", ondelete="CASCADE"), index=True, nullable=True
    )
    scheduled_post_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("scheduled_posts.id", ondelete="CASCADE"), index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Coupon(Base):
    __tablename__ = "coupons"
    __table_args__ = (
        CheckConstraint("months > 0", name="positive_months"),
        CheckConstraint("max_redemptions > 0", name="positive_redemption_limit"),
        CheckConstraint(
            "redeemed_count >= 0 AND redeemed_count <= max_redemptions", name="redemption_capacity"
        ),
        CheckConstraint("benefit_kind = 'free_months'", name="supported_benefit"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("coupon")
    )
    code_digest: Mapped[str] = mapped_column(String(64), unique=True)
    benefit_kind: Mapped[str] = mapped_column(String, default="free_months")
    months: Mapped[int] = mapped_column(Integer)
    max_redemptions: Mapped[int] = mapped_column(Integer, default=1)
    redeemed_count: Mapped[int] = mapped_column(Integer, default=0)
    plan_keys: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claim_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    unclaimable_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    recipient_restricted: Mapped[bool] = mapped_column(Boolean, default=False)
    recipient_key_id: Mapped[Optional[str]] = mapped_column(String(64))
    recipient_fingerprint: Mapped[Optional[str]] = mapped_column(String(64))


class CouponClaim(Base):
    __tablename__ = "coupon_claims"
    __table_args__ = (UniqueConstraint("coupon_id", "key_id", "fingerprint"),)

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("claim")
    )
    coupon_id: Mapped[str] = mapped_column(ForeignKey("coupons.id"), index=True)
    key_id: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))


class CouponHistory(Base):
    __tablename__ = "coupon_history"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


class FreeAccess(Base):
    __tablename__ = "free_access"
    __table_args__ = (
        UniqueConstraint("user_id", "operation_id"),
        CheckConstraint("ends_at > starts_at", name="positive_period"),
        CheckConstraint("months > 0", name="positive_months"),
    )

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("free_access")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    coupon_id: Mapped[str] = mapped_column(ForeignKey("coupons.id"), index=True)
    claim_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("coupon_claims.id", ondelete="SET NULL"), unique=True
    )
    coverage_starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    calendar_anchor: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    month_offset: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    operation_id: Mapped[str] = mapped_column(String(128))
    revision_digest: Mapped[str] = mapped_column(String(64))
    months: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    allowance: Mapped[dict[str, Optional[int]]] = mapped_column(JSON)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acceptance: Mapped[dict] = mapped_column(JSON)


class CouponOperation(Base):
    __tablename__ = "coupon_operations"
    __table_args__ = (UniqueConstraint("user_id", "operation_id"),)

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("coupon_operation")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    coupon_id: Mapped[str] = mapped_column(ForeignKey("coupons.id"), index=True)
    claim_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("coupon_claims.id", ondelete="SET NULL"), unique=True
    )
    operation_id: Mapped[str] = mapped_column(String(128))
    revision_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[Literal["pending", "completed", "refused"]] = mapped_column(
        String, index=True, default="pending"
    )
    customer_id: Mapped[str] = mapped_column(String)
    subscription_id: Mapped[str] = mapped_column(String)
    original: Mapped[dict] = mapped_column(JSON)
    offer: Mapped[dict] = mapped_column(JSON)
    acceptance: Mapped[dict] = mapped_column(JSON)
    target: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    attempted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dispatch_count: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[Optional[str]] = mapped_column(String)


class PaidSignup(Base):
    __tablename__ = "paid_signups"
    __table_args__ = (UniqueConstraint("user_id", "operation_id"),)

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("paid_signup")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    operation_id: Mapped[str] = mapped_column(String(128))
    revision_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[Literal["pending", "completed", "refused"]] = mapped_column(String, index=True)
    creation_state: Mapped[str] = mapped_column(String, default="not_started")
    creation_attempted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    creation_dispatch_count: Mapped[int] = mapped_column(Integer, default=0)
    payment_method_id: Mapped[Optional[str]] = mapped_column(String)
    cancel_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    customer_id: Mapped[Optional[str]] = mapped_column(String)
    session_id: Mapped[Optional[str]] = mapped_column(String)
    subscription_id: Mapped[Optional[str]] = mapped_column(String)
    offer: Mapped[dict] = mapped_column(JSON)
    acceptance: Mapped[dict] = mapped_column(JSON)
    first_payment_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    detail: Mapped[Optional[str]] = mapped_column(String)


class PlanChange(Base):
    __tablename__ = "plan_changes"
    __table_args__ = (UniqueConstraint("user_id", "operation_id"),)

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("plan_change")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    operation_id: Mapped[str] = mapped_column(String(128))
    revision_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[Literal["pending", "completed", "refused"]] = mapped_column(String, index=True)
    customer_id: Mapped[str] = mapped_column(String)
    subscription_id: Mapped[str] = mapped_column(String)
    original: Mapped[dict] = mapped_column(JSON)
    offer: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    dispatch_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    detail: Mapped[Optional[str]] = mapped_column(String)
