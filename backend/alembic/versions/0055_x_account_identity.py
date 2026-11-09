"""Stable X account identity with email retained as nonunique contact information."""

import sqlalchemy as sa

from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_email", type_="unique")
        batch.add_column(sa.Column("x_user_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("x_handle", sa.String(), nullable=True))
        batch.create_unique_constraint("uq_users_x_user_id", ["x_user_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE sign_in_method_enum ADD VALUE IF NOT EXISTS 'x'")


def downgrade() -> None:
    bind = op.get_bind()
    duplicates = bind.scalar(
        sa.text("SELECT email FROM users GROUP BY email HAVING count(*) > 1 LIMIT 1")
    )
    x_sessions = bind.scalar(
        sa.text("SELECT id FROM refresh_tokens WHERE sign_in_method='x' LIMIT 1")
    )
    x_accounts = bind.scalar(sa.text("SELECT id FROM users WHERE x_user_id IS NOT NULL LIMIT 1"))
    if duplicates is not None or x_sessions is not None or x_accounts is not None:
        raise RuntimeError(
            "Downgrade requires unique contact emails, no X accounts and no X sessions; restore a compatible backup instead."
        )
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_x_user_id", type_="unique")
        batch.drop_column("x_handle")
        batch.drop_column("x_user_id")
        batch.create_unique_constraint("uq_users_email", ["email"])
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE sign_in_method_enum RENAME TO sign_in_method_enum_old")
        op.execute("CREATE TYPE sign_in_method_enum AS ENUM ('google', 'magic_link')")
        op.execute(
            "ALTER TABLE refresh_tokens ALTER COLUMN sign_in_method TYPE sign_in_method_enum USING sign_in_method::text::sign_in_method_enum"
        )
        op.execute("DROP TYPE sign_in_method_enum_old")
