from datetime import datetime
from typing import TYPE_CHECKING, Literal, Optional, get_args

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as PgEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pumpkit.core.db.base import Base
from pumpkit.core.ids import ulid_with_prefix

if TYPE_CHECKING:
    from pumpkit.auth.models import User

# Unique and primary key columns are indexed automatically, so they don't set index=True.


class XConnection(Base):
    """
    A User's permission for Pumpkit to publish on one X account (ADR 0006). Tokens are
    Fernet-encrypted; an empty decrypted token means the User must reconnect.
    """

    __tablename__ = "x_connections"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("x_connection")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    # X's own id for the account: a handle can change, this can't.
    x_user_id: Mapped[str] = mapped_column(String, unique=True)
    handle: Mapped[str] = mapped_column(String)
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text)
    access_token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[str] = mapped_column(String)
    # As users/me last reported it; it decides the length limit.
    subscription_type: Mapped[Optional[str]] = mapped_column(String)
    needs_reconnect: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship()


class PendingXAuthorization(Base):
    """
    An X consent screen a User was sent to and hasn't come back from. Kept in the database
    so either API worker can complete it; deleted when used.
    """

    __tablename__ = "pending_x_authorizations"

    # The OAuth state, hashed: it is the only proof the redirect belongs to this User.
    state_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_verifier_encrypted: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (CheckConstraint("expires_at > created_at", name="expires_at_gt_created_at"),)


ScheduledPostState = Literal[
    "scheduled",
    "publishing",
    "published",
    "failed",
]
SCHEDULED: ScheduledPostState = "scheduled"
PUBLISHING: ScheduledPostState = "publishing"
PUBLISHED: ScheduledPostState = "published"
FAILED: ScheduledPostState = "failed"


class ScheduledPost(Base):
    """
    A text a User set to be published on X at a time, with its own copy of the text. It is
    claimed into publishing before X is called, so X is called at most once (ADR 0007).
    """

    __tablename__ = "scheduled_posts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("scheduled_post")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # The X account it goes out on, from the X connection when it was created or rescheduled.
    x_user_id: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    # UTC, whole minutes.
    publish_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[ScheduledPostState] = mapped_column(
        PgEnum(*get_args(ScheduledPostState), name="scheduled_post_state_enum")
    )
    failed_reason: Mapped[Optional[str]] = mapped_column(Text)
    x_post_id: Mapped[Optional[str]] = mapped_column(String)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # The Version whose Final it copied: None when typed, and set to None if the Version goes.
    source_version_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("version_attempts.id", ondelete="SET NULL")
    )
    # 429 backoff: the attempts so far and when the publisher may try again.
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # When it was claimed, so a publisher that crashed mid-call can be recovered from.
    publishing_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship()

    # The publisher looks up due Scheduled posts by state and time.
    __table_args__ = (Index("ix_scheduled_posts_state_publish_at", "state", "publish_at"),)
