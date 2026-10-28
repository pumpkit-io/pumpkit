from datetime import datetime
from typing import TYPE_CHECKING, Literal, Optional, get_args

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pumpkit.core.db.base import Base
from pumpkit.core.ids import ulid_with_prefix

if TYPE_CHECKING:
    from pumpkit.auth.models import User

# Unique and primary key columns are indexed automatically, so they don't set index=True.


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
    A text a User set to be published on X at a time, with its own copy of the text as Parts.
    It is claimed into publishing before X is called, so X is called at most once (ADR 0007).
    """

    __tablename__ = "scheduled_posts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("scheduled_post")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # The X account it goes out on, from the X connection when it was created or rescheduled.
    x_user_id: Mapped[str] = mapped_column(String)
    # The Community it goes to, None for the profile, with its name as shown when it was picked.
    community_id: Mapped[Optional[str]] = mapped_column(String)
    community_name: Mapped[Optional[str]] = mapped_column(String)
    # When the Community was last set on it, which orders the Communities offered again.
    community_set_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # With a Community, whether X also shows it on the profile and in the followers' timelines.
    share_with_followers: Mapped[bool] = mapped_column(Boolean, default=False)
    # UTC, whole minutes.
    publish_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[ScheduledPostState] = mapped_column(
        PgEnum(*get_args(ScheduledPostState), name="scheduled_post_state_enum")
    )
    failed_reason: Mapped[Optional[str]] = mapped_column(Text)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # The Version whose text it copied (ADR 0015).
    source_version_id: Mapped[str] = mapped_column(
        ForeignKey("version_attempts.id", ondelete="CASCADE")
    )
    # That Version's Post. Unique, so a Post goes out at most once (ADR 0015).
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), unique=True)
    # 429 backoff: the attempts so far and when the publisher may try again.
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # When it was claimed, so a publisher that crashed mid-call can be recovered from.
    publishing_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship()
    # One Part is a single X post; several are a Thread.
    parts: Mapped[list["ScheduledPostPart"]] = relationship(
        back_populates="scheduled_post",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ScheduledPostPart.position",
        lazy="selectin",
    )

    # The publisher looks up due Scheduled posts by state and time.
    __table_args__ = (Index("ix_scheduled_posts_state_publish_at", "state", "publish_at"),)


class ScheduledPostPart(Base):
    """One X post of a Scheduled post, in its place in the order."""

    __tablename__ = "scheduled_post_parts"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("scheduled_post_part")
    )
    scheduled_post_id: Mapped[str] = mapped_column(
        ForeignKey("scheduled_posts.id", ondelete="CASCADE")
    )
    # From 0, the order the Parts go out in.
    position: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    # Set once X accepts this Part: it is live and can no longer change.
    x_post_id: Mapped[Optional[str]] = mapped_column(String)

    scheduled_post: Mapped[ScheduledPost] = relationship(back_populates="parts")

    # The unique index also serves the lookup of a Scheduled post's Parts.
    __table_args__ = (UniqueConstraint("scheduled_post_id", "position"),)
