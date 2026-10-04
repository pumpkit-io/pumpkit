"""drop password auth

Drops the password ("first-party") auth tables and the `local` value of
auth_method_enum (see docs/adr/0002-google-and-magic-link-only.md). No deployment
holds real users, so no user data is migrated. The downgrade recreates the tables
empty.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("password_resets", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_password_resets_password_resets_user_id"))
    op.drop_table("password_resets")

    with op.batch_alter_table("email_verifications", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_email_verifications_email_verifications_user_id"))
    op.drop_table("email_verifications")

    op.drop_table("first_party_auth")

    # Postgres can't drop a value from an enum type, so swap in a new type.
    # Sessions opened with a password can no longer be refreshed, so drop them.
    op.execute("DELETE FROM auth_sessions WHERE auth_method = 'local'")
    _replace_auth_method_enum(("google", "magic_link"))


def downgrade() -> None:
    _replace_auth_method_enum(("local", "google", "magic_link"))

    op.create_table(
        "first_party_auth",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("is_email_verified", sa.Boolean(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column(
            "password_set_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_first_party_auth_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_first_party_auth")),
        sa.UniqueConstraint("user_id", name=op.f("uq_first_party_auth_user_id")),
    )

    op.create_table(
        "email_verifications",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("email_to_verify", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at > sent_at", name=op.f("ck_email_verifications_expires_at_gt_sent_at")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_email_verifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_verifications")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_email_verifications_token_hash")),
    )
    with op.batch_alter_table("email_verifications", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_email_verifications_email_verifications_user_id"),
            ["user_id"],
            unique=False,
        )

    op.create_table(
        "password_resets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expires_at > sent_at", name=op.f("ck_password_resets_expires_at_gt_sent_at")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_password_resets_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_resets")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_password_resets_token_hash")),
    )
    with op.batch_alter_table("password_resets", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_password_resets_password_resets_user_id"), ["user_id"], unique=False
        )


def _replace_auth_method_enum(values: tuple[str, ...]) -> None:
    """Recreate auth_method_enum with the given values and repoint auth_sessions at it."""
    labels = ", ".join(f"'{value}'" for value in values)
    op.execute("ALTER TYPE auth_method_enum RENAME TO auth_method_enum_old")
    op.execute(f"CREATE TYPE auth_method_enum AS ENUM ({labels})")
    op.execute(
        "ALTER TABLE auth_sessions ALTER COLUMN auth_method "
        "TYPE auth_method_enum USING auth_method::text::auth_method_enum"
    )
    op.execute("DROP TYPE auth_method_enum_old")
