from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text
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
