from datetime import datetime
from typing import Literal, Optional, get_args

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy import (
    Enum as PgEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pumpkit.core.db.base import Base
from pumpkit.core.ids import ulid_with_prefix

# See docs/adr/0020-*.md. Every secret is stored as a SHA-256 hash.
OAuthClientKind = Literal["registered", "metadata_document"]


class OAuthClient(Base):
    """
    An app's registration: made through Dynamic Client Registration, or fetched from the
    metadata document its client id points to. The id is the document's URL for the latter.
    """

    __tablename__ = "oauth_clients"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("oauth_client")
    )
    kind: Mapped[OAuthClientKind] = mapped_column(
        PgEnum(*get_args(OAuthClientKind), name="oauth_client_kind")
    )
    name: Mapped[str] = mapped_column(String)
    redirect_uris: Mapped[list[str]] = mapped_column(JSON().with_variant(JSONB(), "postgresql"))
    # 'none', 'client_secret_post' or 'client_secret_basic'.
    token_endpoint_auth_method: Mapped[str] = mapped_column(String)
    client_secret_hash: Mapped[Optional[str]] = mapped_column(String)
    client_uri: Mapped[Optional[str]] = mapped_column(String)
    logo_uri: Mapped[Optional[str]] = mapped_column(String)
    software_id: Mapped[Optional[str]] = mapped_column(String)
    software_version: Mapped[Optional[str]] = mapped_column(String)
    metadata_fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AppConnection(Base):
    """
    A User's grant to an app: a Connected app. Disconnecting sets `revoked_at`, and token
    checks refuse a revoked connection.
    """

    __tablename__ = "app_connections"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("app_connection")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.id", ondelete="CASCADE"), index=True
    )
    scope: Mapped[str] = mapped_column(String)
    resource: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_app_connections_user_id_revoked_at", "user_id", "revoked_at"),)


class OAuthAuthorization(Base):
    """One consent request and, once approved, its single-use authorization code."""

    __tablename__ = "oauth_authorizations"

    # Random, not a ULID: it appears in the consent page's URL.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.id", ondelete="CASCADE"))
    redirect_uri: Mapped[str] = mapped_column(String)
    # Whether the token request must repeat the redirect URI (RFC 6749 section 4.1.3).
    redirect_uri_was_sent: Mapped[bool] = mapped_column(Boolean)
    code_challenge: Mapped[str] = mapped_column(String)
    scope: Mapped[str] = mapped_column(String)
    resource: Mapped[str] = mapped_column(String)
    state: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    app_connection_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("app_connections.id", ondelete="CASCADE")
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approved: Mapped[Optional[bool]] = mapped_column(Boolean)
    code_hash: Mapped[Optional[str]] = mapped_column(String, unique=True)
    code_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    exchanged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("expires_at > created_at", name="expires_at_gt_created_at"),)


class OAuthRefreshToken(Base):
    __tablename__ = "oauth_refresh_tokens"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("oauth_refresh_token")
    )
    app_connection_id: Mapped[str] = mapped_column(
        ForeignKey("app_connections.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[Optional[str]] = mapped_column(
        ForeignKey("oauth_refresh_tokens.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("expires_at > created_at", name="expires_at_gt_created_at"),)


class OAuthAccessToken(Base):
    __tablename__ = "oauth_access_tokens"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: ulid_with_prefix("oauth_access_token")
    )
    app_connection_id: Mapped[str] = mapped_column(
        ForeignKey("app_connections.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("expires_at > created_at", name="expires_at_gt_created_at"),)
