from datetime import datetime
from typing import Literal, Optional, get_args

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
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


AuthMethod = Literal[
    # Third-party authentication
    "google",
    # Passwordless authentication
    "magic_link",
]

ThirdPartyAuthProvider = Literal["google",]

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

PurchaseStatus = Literal[
    "pending",
    "paid",
    "refunded",
    "partially_refunded",
    "disputed",
    "failed",
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

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    banned_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Stripe
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)

    # Relationships
    third_party_auth: Mapped[list["ThirdPartyAuth"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    magic_links: Mapped[list["MagicLink"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    purchases: Mapped[list["Purchase"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    auth_sessions: Mapped[list["AuthSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ThirdPartyAuth(Base):
    """
    Data for third-party authentication, based on OAuth
    """

    __tablename__ = "third_party_auth"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("third_party_auth")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[ThirdPartyAuthProvider] = mapped_column(
        PgEnum(*get_args(ThirdPartyAuthProvider), name="third_party_auth_provider_enum"), index=True
    )

    # OAuth response
    subject: Mapped[str] = mapped_column(String, index=True)
    id_token_encrypted: Mapped[Optional[str]] = mapped_column(Text)
    # JSONB on Postgres; JSON variant lets the SQLite test DB create the table.
    profile_json: Mapped[Optional[dict]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="third_party_auth")

    __table_args__ = (
        # A logged user can link the same provider multiple times only if the subject differs (i.e., the connected account is different)
        UniqueConstraint(
            "user_id", "provider", "subject", name="uq_third_party_auth_user_id_provider_subject"
        ),
    )


class AuthSession(Base):
    """
    Sessions of authenticated users
    """

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("auth_session")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    # Authentication method
    auth_method: Mapped[AuthMethod] = mapped_column(
        PgEnum(*get_args(AuthMethod), name="auth_method_enum"), index=True
    )

    # Refresh token lineage and rotation
    family_id: Mapped[str] = mapped_column(
        String, index=True
    )  # Refresh tokens belonging to the same lineage share the same family ID
    refresh_token_hash: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL")
    )  # ID of the newer refresh token that replaced this one

    # Refresh token status
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Audit
    ip: Mapped[Optional[str]] = mapped_column(String)
    user_agent: Mapped[Optional[str]] = mapped_column(String)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="auth_sessions")

    __table_args__ = (
        # Helps housekeeping queries
        Index("ix_auth_sessions_user_id_is_revoked", "user_id", "is_revoked"),
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
    Local replica of Stripe subscription state for fast access to important fields
    (don't hit Stripe API for every check). Updated via Stripe webhooks.
    """

    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("subscription")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    stripe_subscription_id: Mapped[str] = mapped_column(String, unique=True)
    stripe_customer_id: Mapped[str] = mapped_column(String, index=True)
    stripe_price_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
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


class Purchase(Base):
    """One-time Stripe Checkout purchase of a catalog product (app/core/purchases.py).

    Created ``pending`` when the Checkout Session is created and moved through
    its lifecycle by the Stripe webhook. What a purchase unlocks is decided in
    app/api/hooks/purchases.py.
    """

    __tablename__ = "purchases"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("purchase")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str] = mapped_column(String, index=True)

    status: Mapped[PurchaseStatus] = mapped_column(
        PgEnum(*get_args(PurchaseStatus), name="purchase_status_enum"),
        index=True,
        default="pending",
    )

    stripe_checkout_session_id: Mapped[str] = mapped_column(String, unique=True)
    stripe_payment_intent_id: Mapped[Optional[str]] = mapped_column(
        String, index=True, nullable=True
    )
    stripe_charge_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)

    currency: Mapped[str] = mapped_column(String)
    amount_subtotal_cents: Mapped[int] = mapped_column(BigInteger)
    amount_tax_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    amount_total_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    refunded_amount_cents: Mapped[int] = mapped_column(BigInteger, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="purchases")

    __table_args__ = (Index("ix_purchases_user_id_created_at", "user_id", "created_at"),)
