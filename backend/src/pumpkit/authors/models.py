from datetime import datetime
from typing import TYPE_CHECKING, Optional

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


# Where a directory entry came from: the seed list every Instance starts with, or X.
SOURCE_SEED = "seed"
SOURCE_LOOKUP = "lookup"


class AuthorDirectoryEntry(Base):
    """
    An X account in the Author directory, the one home of its name and photo. Entries are never
    deleted, so an account nobody lists any more stays for the next User to pick.
    """

    __tablename__ = "author_directory"

    # Normalised: no @, lowercased, as on an Inspiration author.
    handle: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # X's URL for the photo, never a copy; the browser loads it from X.
    photo_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String)
