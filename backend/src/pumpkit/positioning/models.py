from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pumpkit.core.db.base import Base
from pumpkit.core.ids import ulid_with_prefix

if TYPE_CHECKING:
    from pumpkit.auth.models import User


class Positioning(Base):
    """
    A User's Positioning: one free text saying who they are on X, what they post about, who they
    write for, what they post for and what they can point readers to. A User has at most one.
    """

    __tablename__ = "positionings"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    text: Mapped[str] = mapped_column(Text)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship()


class PositioningDraftRequest(Base):
    """
    One request for a draft of a User's Positioning that went on to read X. The daily limit
    counts these, so it holds across restarts and processes.
    """

    __tablename__ = "positioning_draft_requests"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("positioning_draft")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
