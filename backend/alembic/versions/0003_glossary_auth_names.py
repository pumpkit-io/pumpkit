"""rename auth tables to the glossary

Renames the auth schema to the language in GLOSSARY.md, with no behaviour change:
- `auth_sessions` becomes `refresh_tokens`; `family_id` becomes `session_id` (a Session
  is the set of refresh tokens sharing a `session_id`); `auth_method` and its enum
  become `sign_in_method` / `sign_in_method_enum`.
- `third_party_auth` becomes `google_identities`, and its `provider` column and enum are
  dropped: Google is the only OAuth Sign-in method (docs/adr/0002-google-and-magic-link-only.md).
- On `users`, `is_active` and `banned_until` become a single nullable `suspended_until`.

No deployment holds real users, so nothing is backfilled.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-04 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (old name, new name) for the constraints of refresh_tokens
_REFRESH_TOKEN_CONSTRAINTS = [
    ("pk_auth_sessions", "pk_refresh_tokens"),
    ("uq_auth_sessions_refresh_token_hash", "uq_refresh_tokens_refresh_token_hash"),
    ("ck_auth_sessions_expires_at_gt_created_at", "ck_refresh_tokens_expires_at_gt_created_at"),
    (
        "fk_auth_sessions_replaced_by_auth_sessions",
        "fk_refresh_tokens_replaced_by_refresh_tokens",
    ),
    ("fk_auth_sessions_user_id_users", "fk_refresh_tokens_user_id_users"),
]

# (old name, new name) for the indexes of refresh_tokens
_REFRESH_TOKEN_INDEXES = [
    (
        "ix_auth_sessions_auth_sessions_auth_method",
        "ix_refresh_tokens_refresh_tokens_sign_in_method",
    ),
    ("ix_auth_sessions_auth_sessions_family_id", "ix_refresh_tokens_refresh_tokens_session_id"),
    ("ix_auth_sessions_auth_sessions_user_id", "ix_refresh_tokens_refresh_tokens_user_id"),
    ("ix_auth_sessions_user_id_is_revoked", "ix_refresh_tokens_user_id_is_revoked"),
]

# (old name, new name) for the constraints of google_identities
_GOOGLE_IDENTITY_CONSTRAINTS = [
    ("pk_third_party_auth", "pk_google_identities"),
    ("fk_third_party_auth_user_id_users", "fk_google_identities_user_id_users"),
]

# (old name, new name) for the indexes of google_identities
_GOOGLE_IDENTITY_INDEXES = [
    (
        "ix_third_party_auth_third_party_auth_subject",
        "ix_google_identities_google_identities_subject",
    ),
    (
        "ix_third_party_auth_third_party_auth_user_id",
        "ix_google_identities_google_identities_user_id",
    ),
]


def upgrade() -> None:
    # users: one nullable `suspended_until` replaces `is_active` and `banned_until`
    op.alter_column("users", "banned_until", new_column_name="suspended_until")
    op.drop_column("users", "is_active")

    # auth_sessions -> refresh_tokens
    op.rename_table("auth_sessions", "refresh_tokens")
    op.alter_column("refresh_tokens", "family_id", new_column_name="session_id")
    op.alter_column("refresh_tokens", "auth_method", new_column_name="sign_in_method")
    op.execute("ALTER TYPE auth_method_enum RENAME TO sign_in_method_enum")
    _rename_constraints("refresh_tokens", _REFRESH_TOKEN_CONSTRAINTS)
    _rename_indexes(_REFRESH_TOKEN_INDEXES)

    # third_party_auth -> google_identities, without the provider
    op.drop_constraint(
        "uq_third_party_auth_user_id_provider_subject", "third_party_auth", type_="unique"
    )
    op.drop_index("ix_third_party_auth_third_party_auth_provider", table_name="third_party_auth")
    op.drop_column("third_party_auth", "provider")
    op.execute("DROP TYPE third_party_auth_provider_enum")
    op.rename_table("third_party_auth", "google_identities")
    _rename_constraints("google_identities", _GOOGLE_IDENTITY_CONSTRAINTS)
    _rename_indexes(_GOOGLE_IDENTITY_INDEXES)
    op.create_unique_constraint(
        "uq_google_identities_user_id_subject", "google_identities", ["user_id", "subject"]
    )


def downgrade() -> None:
    # google_identities -> third_party_auth, with the provider back
    op.drop_constraint("uq_google_identities_user_id_subject", "google_identities", type_="unique")
    _rename_indexes(_swap(_GOOGLE_IDENTITY_INDEXES))
    _rename_constraints("google_identities", _swap(_GOOGLE_IDENTITY_CONSTRAINTS))
    op.rename_table("google_identities", "third_party_auth")
    op.execute("CREATE TYPE third_party_auth_provider_enum AS ENUM ('google')")
    op.add_column(
        "third_party_auth",
        sa.Column(
            "provider",
            sa.Enum("google", name="third_party_auth_provider_enum", create_type=False),
            server_default="google",
            nullable=False,
        ),
    )
    op.alter_column("third_party_auth", "provider", server_default=None)
    op.create_index(
        "ix_third_party_auth_third_party_auth_provider",
        "third_party_auth",
        ["provider"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_third_party_auth_user_id_provider_subject",
        "third_party_auth",
        ["user_id", "provider", "subject"],
    )

    # refresh_tokens -> auth_sessions
    _rename_indexes(_swap(_REFRESH_TOKEN_INDEXES))
    _rename_constraints("refresh_tokens", _swap(_REFRESH_TOKEN_CONSTRAINTS))
    op.execute("ALTER TYPE sign_in_method_enum RENAME TO auth_method_enum")
    op.alter_column("refresh_tokens", "sign_in_method", new_column_name="auth_method")
    op.alter_column("refresh_tokens", "session_id", new_column_name="family_id")
    op.rename_table("refresh_tokens", "auth_sessions")

    # users: back to `is_active` and `banned_until`
    op.add_column(
        "users",
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.alter_column("users", "is_active", server_default=None)
    op.alter_column("users", "suspended_until", new_column_name="banned_until")


def _swap(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(new, old) for old, new in pairs]


def _rename_constraints(table: str, pairs: list[tuple[str, str]]) -> None:
    for old, new in pairs:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {old} TO {new}")


def _rename_indexes(pairs: list[tuple[str, str]]) -> None:
    for old, new in pairs:
        op.execute(f"ALTER INDEX {old} RENAME TO {new}")
