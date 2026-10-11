from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pumpkit.core.db.base import Base
from pumpkit.core.ids import ulid_with_prefix

if TYPE_CHECKING:
    from pumpkit.auth.models import User

# Unique and primary key columns are indexed automatically, so they don't set index=True.


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

    user: Mapped["User"] = relationship()

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
