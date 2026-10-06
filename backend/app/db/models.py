from datetime import datetime
from typing import Literal, Optional, get_args

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as PgEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import ulid_with_prefix
from app.db.base import Base

# Notes on SQLAlchemy:
# - An index is automatically created for each unique/primary key column (no need to set index=True)
# - The naming conventions SQLAlchemy will follow when creating DB indexes and constraints are defined in backend/app/db/base.py


# The ways a User can sign in (see docs/adr/0002-google-and-magic-link-only.md)
SignInMethod = Literal[
    "google",
    "magic_link",
]

# All possible subscription statuses according to Stripe documentation: https://stripe.com/docs/billing/subscriptions/overview#subscription-statuses
SubscriptionStatus = Literal[
    "trialing",
    "active",
    "incomplete",
    "incomplete_expired",
    "past_due",
    "canceled",
    "unpaid",
    "paused",
]


class User(Base):
    """
    Users data
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("user")
    )

    # User
    email: Mapped[str] = mapped_column(String, unique=True)
    display_name: Mapped[str] = mapped_column(String)
    first_name: Mapped[Optional[str]] = mapped_column(String)
    last_name: Mapped[Optional[str]] = mapped_column(String)
    avatar_data_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Account
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    # Suspension: NULL means not Suspended; a future date means Suspended until then
    # (a permanent suspension uses a far-future date)
    suspended_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Stripe
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)

    # Relationships
    google_identities: Mapped[list["GoogleIdentity"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    magic_links: Mapped[list["MagicLink"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class GoogleIdentity(Base):
    """
    The link between a User and the Google account they sign in with
    """

    __tablename__ = "google_identities"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("google_identity")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    # OAuth response
    # A Google account links to at most one User
    subject: Mapped[str] = mapped_column(String, unique=True)
    id_token_encrypted: Mapped[Optional[str]] = mapped_column(Text)
    # JSONB on Postgres; JSON variant lets the SQLite test DB create the table.
    profile_json: Mapped[Optional[dict]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="google_identities")


class RefreshToken(Base):
    """
    A refresh token issued to a User. A Session is the set of refresh tokens that
    share a `session_id`: each rotation adds a token to the same Session.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("refresh_token")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    # The Sign-in method that started the Session
    sign_in_method: Mapped[SignInMethod] = mapped_column(
        PgEnum(*get_args(SignInMethod), name="sign_in_method_enum"), index=True
    )

    # Session membership and rotation
    session_id: Mapped[str] = mapped_column(String, index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )  # ID of the newer refresh token that replaced this one

    # Refresh token status
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Audit
    ip: Mapped[Optional[str]] = mapped_column(String)
    user_agent: Mapped[Optional[str]] = mapped_column(String)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    __table_args__ = (
        # Helps housekeeping queries
        Index("ix_refresh_tokens_user_id_is_revoked", "user_id", "is_revoked"),
        # Sanity check on expiration timestamp
        CheckConstraint("expires_at > created_at", name="expires_at_gt_created_at"),
    )


class MagicLink(Base):
    """
    One-time token used to sign a user in via magic link.

    A MagicLink can exist before the User exists: a request for an unknown email creates a
    row with user_id=NULL, and the User is created on consume.
    """

    __tablename__ = "magic_links"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("magic_link")
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # The email the link was requested for. We trust THIS email at consume time,
    # not anything from the click URL. Lowercased at request time.
    email: Mapped[str] = mapped_column(String, index=True)

    # Token information
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Audit
    requester_ip: Mapped[Optional[str]] = mapped_column(String)
    requester_user_agent: Mapped[Optional[str]] = mapped_column(String)

    # Relationships
    user: Mapped[Optional["User"]] = relationship(back_populates="magic_links")

    __table_args__ = (CheckConstraint("expires_at > sent_at", name="expires_at_gt_sent_at"),)


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="subscriptions")


class StripeEvent(Base):
    """Idempotency log for processed Stripe webhook events.

    Insert succeeds only the first time a given ``event.id`` is seen; the
    webhook dispatcher uses this to short-circuit replays.
    """

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
