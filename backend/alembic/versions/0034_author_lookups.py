"""the lookup log and miss memory for handles looked up on X

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-31 21:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "author_handle_misses",
        sa.Column("handle", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("remembered_until", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("handle", name=op.f("pk_author_handle_misses")),
    )
    op.create_table(
        "author_lookups",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=True),
        sa.Column("handle", sa.String(), nullable=False),
        sa.Column("looked_up_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_author_lookups_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_author_lookups")),
    )
    with op.batch_alter_table("author_lookups", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_author_lookups_author_lookups_user_id"), ["user_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_author_lookups_author_lookups_looked_up_at"),
            ["looked_up_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("author_lookups", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_author_lookups_author_lookups_looked_up_at"))
        batch_op.drop_index(batch_op.f("ix_author_lookups_author_lookups_user_id"))
    op.drop_table("author_lookups")
    op.drop_table("author_handle_misses")
