from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pumpkit.core.db.base import Base

if TYPE_CHECKING:
    from pumpkit.auth.models import User


class OnboardingFinish(Base):
    """
    That a User finished Onboarding: the one fact Onboarding stores, since every step's "done" is
    read from data and finishing must outlast emptying the Persona or disconnecting X (ADR 0018).
    """

    __tablename__ = "onboarding_finishes"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship()
