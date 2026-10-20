"""add the hook step's library id, model and usage to Version attempts

A first Version's Draft may open with a Hook from the curated library. Its attempt stores which
one (or "none") with the hook call's model and usage, like the writing and humanizer calls'. All
three stay null when the hook step didn't run or failed.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-20 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("hook_name", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("hooking_model", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "hooking_usage",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.drop_column("hooking_usage")
        batch_op.drop_column("hooking_model")
        batch_op.drop_column("hook_name")
