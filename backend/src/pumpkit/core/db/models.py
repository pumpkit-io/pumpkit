from datetime import datetime
from typing import TYPE_CHECKING, Literal, Optional, get_args

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as PgEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pumpkit.core.db.base import Base
from pumpkit.core.ids import ulid_with_prefix

if TYPE_CHECKING:
    from pumpkit.auth.models import User

# Unique and primary key columns are indexed automatically, so they don't set index=True.


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

    user: Mapped["User"] = relationship()
    attempts: Mapped[list["VersionAttempt"]] = relationship(
        back_populates="post", cascade="all, delete-orphan", order_by="VersionAttempt.sequence"
    )


VersionAttemptStatus = Literal[
    "succeeded",
    "failed",
]
ATTEMPT_SUCCEEDED: VersionAttemptStatus = "succeeded"
ATTEMPT_FAILED: VersionAttemptStatus = "failed"


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
    # The slop check's tells in the Final, each {"name", "description"}, in the check's order.
    slop_tells: Mapped[Optional[list[dict]]] = mapped_column(
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
