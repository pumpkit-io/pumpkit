"""the plan calls a User made, which the hourly cap on planning counts

Revision ID: 0065
Revises: 0064
Create Date: 2026-11-15 08:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0065"
down_revision: Union[str, None] = "0064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plan_calls",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("called_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_plan_calls_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_calls")),
    )
    op.create_index(
        op.f("ix_plan_calls_plan_calls_user_id"), "plan_calls", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_plan_calls_plan_calls_user_id"), table_name="plan_calls")
    op.drop_table("plan_calls")
