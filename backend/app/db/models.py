from datetime import datetime
from typing import Literal, Optional, get_args

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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
from app.core.subscription_status import SubscriptionStatus
from app.db.base import Base

# Unique and primary key columns are indexed automatically, so they don't set index=True.


# See docs/adr/0002-google-and-magic-link-only.md.
SignInMethod = Literal[
    "google",
    "magic_link",
]


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("user")
    )

    email: Mapped[str] = mapped_column(String, unique=True)
    display_name: Mapped[str] = mapped_column(String)
    first_name: Mapped[Optional[str]] = mapped_column(String)
    last_name: Mapped[Optional[str]] = mapped_column(String)
    avatar_data_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    # Suspension: NULL means not Suspended; a future date means Suspended until then
    # (a permanent suspension uses a far-future date)
    suspended_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)

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
    inspiration_authors: Mapped[list["InspirationAuthor"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    posts: Mapped[list["Post"]] = relationship(back_populates="user", cascade="all, delete-orphan")


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
    subject: Mapped[str] = mapped_column(String, unique=True)
    id_token_encrypted: Mapped[Optional[str]] = mapped_column(Text)
    # JSONB on Postgres; JSON variant lets the SQLite test DB create the table.
    profile_json: Mapped[Optional[dict]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

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

    session_id: Mapped[str] = mapped_column(String, index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )

    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Audit
    ip: Mapped[Optional[str]] = mapped_column(String)
    user_agent: Mapped[Optional[str]] = mapped_column(String)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    __table_args__ = (
        # Helps housekeeping queries
        Index("ix_refresh_tokens_user_id_is_revoked", "user_id", "is_revoked"),
        CheckConstraint("expires_at > created_at", name="expires_at_gt_created_at"),
    )


class MagicLink(Base):
    """
    One-time sign-in token. It can exist before its User: a request for an unknown
    email stores user_id=NULL, and the User is created on consume.
    """

    __tablename__ = "magic_links"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("magic_link")
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # Consume trusts this email, never anything from the click URL.
    # Lowercased at request time.
    email: Mapped[str] = mapped_column(String, index=True)

    token_hash: Mapped[str] = mapped_column(String, unique=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Audit
    requester_ip: Mapped[Optional[str]] = mapped_column(String)
    requester_user_agent: Mapped[Optional[str]] = mapped_column(String)

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
    # When Stripe created the Subscription: the order between a User's
    # Subscriptions, since rows synced in one transaction share `created_at`.
    stripe_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="subscriptions")


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


class InspirationAuthor(Base):
    """
    An X handle on a User's list of Inspiration authors. Removing one deletes only this
    row: the author's fetched posts stay, because stored Posts reference them.
    """

    __tablename__ = "inspiration_authors"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("inspiration_author")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Normalised: no @, lowercased, so handles compare case-insensitively.
    handle: Mapped[str] = mapped_column(String)
    # The list order; gaps left by removals are fine.
    position: Mapped[int] = mapped_column(Integer)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="inspiration_authors")

    __table_args__ = (UniqueConstraint("user_id", "handle"),)


class AuthorPost(Base):
    """
    An original post or quote fetched from X, shared by every User who lists its author.
    A refetch inserts only posts not already stored.
    """

    __tablename__ = "author_posts"

    # X's post id.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    handle: Mapped[str] = mapped_column(String, index=True)
    text: Mapped[str] = mapped_column(Text)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuthorFetch(Base):
    """When a handle's posts were last fetched, shared by every User who lists it."""

    __tablename__ = "author_fetches"

    handle: Mapped[str] = mapped_column(String, primary_key=True)
    last_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Post(Base):
    """One piece of writing made from one Brief, with every attempt at a Version of it."""

    __tablename__ = "posts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("post")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    brief: Mapped[str] = mapped_column(Text)
    # The corpus's author post ids in the order the calls get them, fixed when the Post starts
    # so changing the User's Inspiration authors later doesn't change it.
    corpus_post_ids: Mapped[list[str]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="posts")
    attempts: Mapped[list["VersionAttempt"]] = relationship(
        back_populates="post", cascade="all, delete-orphan", order_by="VersionAttempt.sequence"
    )


VersionAttemptStatus = Literal[
    "succeeded",
    "failed",
]


class VersionAttempt(Base):
    """
    One try at writing a Version of a Post. Only a succeeded attempt is a Version; a failed
    one keeps its error instead.
    """

    __tablename__ = "version_attempts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("version_attempt")
    )
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    # Counts every attempt on the Post, failed ones included.
    sequence: Mapped[int] = mapped_column(Integer)
    # None for the first Version, which comes from the Brief.
    feedback: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[VersionAttemptStatus] = mapped_column(
        PgEnum(*get_args(VersionAttemptStatus), name="version_attempt_status_enum")
    )
    # Counts succeeded attempts only: the number the User sees.
    version_number: Mapped[Optional[int]] = mapped_column(Integer)
    draft: Mapped[Optional[str]] = mapped_column(Text)
    final: Mapped[Optional[str]] = mapped_column(Text)
    final_char_count: Mapped[Optional[int]] = mapped_column(Integer)
    # The draft call's model on a first Version, the revision call's on a later one.
    writing_model: Mapped[Optional[str]] = mapped_column(String)
    humanizing_model: Mapped[Optional[str]] = mapped_column(String)
    # The provider's whole usage payload, cost and cache counts included.
    writing_usage: Mapped[Optional[dict]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    humanizing_usage: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    post: Mapped["Post"] = relationship(back_populates="attempts")

    __table_args__ = (
        # Named here: the naming convention uses only the first column, so the two would clash.
        UniqueConstraint("post_id", "sequence", name="uq_version_attempts_post_id_sequence"),
        UniqueConstraint(
            "post_id", "version_number", name="uq_version_attempts_post_id_version_number"
        ),
    )
