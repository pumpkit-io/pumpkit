"""add Connected apps

An AI app reaches the MCP server with OAuth (ADR 0020). `oauth_clients` holds each app's
registration, `app_connections` a User's connection to an app (the Connected app they see and
disconnect), `oauth_authorizations` each consent request with its single-use code, and
`oauth_refresh_tokens` and `oauth_access_tokens` the tokens issued. Every secret is stored as a
SHA-256 hash. Connections, tokens and requests go with the User's account.

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-01 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KIND = sa.Enum("registered", "metadata_document", name="oauth_client_kind")
_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _timestamp(name: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("kind", _KIND, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("redirect_uris", _JSON, nullable=False),
        sa.Column("token_endpoint_auth_method", sa.String(), nullable=False),
        sa.Column("client_secret_hash", sa.String(), nullable=True),
        sa.Column("client_uri", sa.String(), nullable=True),
        sa.Column("logo_uri", sa.String(), nullable=True),
        sa.Column("software_id", sa.String(), nullable=True),
        sa.Column("software_version", sa.String(), nullable=True),
        _timestamp("metadata_fetched_at", nullable=True),
        _timestamp("created_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_clients")),
    )

    op.create_table(
        "app_connections",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("resource", sa.String(), nullable=False),
        _timestamp("created_at"),
        _timestamp("last_used_at", nullable=True),
        _timestamp("revoked_at", nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_app_connections_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.id"],
            name=op.f("fk_app_connections_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_connections")),
    )
    with op.batch_alter_table("app_connections", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_app_connections_app_connections_user_id"), ["user_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_app_connections_app_connections_client_id"),
            ["client_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_app_connections_user_id_revoked_at", ["user_id", "revoked_at"], unique=False
        )

    op.create_table(
        "oauth_authorizations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("redirect_uri", sa.String(), nullable=False),
        sa.Column("redirect_uri_was_sent", sa.Boolean(), nullable=False),
        sa.Column("code_challenge", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("resource", sa.String(), nullable=False),
        sa.Column("state", sa.Text(), nullable=True),
        _timestamp("created_at"),
        _timestamp("expires_at"),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("app_connection_id", sa.String(), nullable=True),
        _timestamp("decided_at", nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=True),
        sa.Column("code_hash", sa.String(), nullable=True),
        _timestamp("code_expires_at", nullable=True),
        _timestamp("exchanged_at", nullable=True),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_oauth_authorizations_expires_at_gt_created_at"),
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["oauth_clients.id"],
            name=op.f("fk_oauth_authorizations_client_id_oauth_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_oauth_authorizations_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["app_connection_id"],
            ["app_connections.id"],
            name=op.f("fk_oauth_authorizations_app_connection_id_app_connections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_authorizations")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_oauth_authorizations_code_hash")),
    )

    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("app_connection_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        _timestamp("created_at"),
        _timestamp("expires_at"),
        _timestamp("rotated_at", nullable=True),
        sa.Column("replaced_by", sa.String(), nullable=True),
        _timestamp("revoked_at", nullable=True),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_oauth_refresh_tokens_expires_at_gt_created_at"),
        ),
        sa.ForeignKeyConstraint(
            ["app_connection_id"],
            ["app_connections.id"],
            name=op.f("fk_oauth_refresh_tokens_app_connection_id_app_connections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by"],
            ["oauth_refresh_tokens.id"],
            name=op.f("fk_oauth_refresh_tokens_replaced_by_oauth_refresh_tokens"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_oauth_refresh_tokens_token_hash")),
    )
    with op.batch_alter_table("oauth_refresh_tokens", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_oauth_refresh_tokens_oauth_refresh_tokens_app_connection_id"),
            ["app_connection_id"],
            unique=False,
        )

    op.create_table(
        "oauth_access_tokens",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("app_connection_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        _timestamp("created_at"),
        _timestamp("expires_at"),
        _timestamp("revoked_at", nullable=True),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_oauth_access_tokens_expires_at_gt_created_at"),
        ),
        sa.ForeignKeyConstraint(
            ["app_connection_id"],
            ["app_connections.id"],
            name=op.f("fk_oauth_access_tokens_app_connection_id_app_connections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_access_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_oauth_access_tokens_token_hash")),
    )
    with op.batch_alter_table("oauth_access_tokens", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_oauth_access_tokens_oauth_access_tokens_app_connection_id"),
            ["app_connection_id"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("oauth_access_tokens")
    op.drop_table("oauth_refresh_tokens")
    op.drop_table("oauth_authorizations")
    op.drop_table("app_connections")
    op.drop_table("oauth_clients")
    _KIND.drop(op.get_bind(), checkfirst=True)
