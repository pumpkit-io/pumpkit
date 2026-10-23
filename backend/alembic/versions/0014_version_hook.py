"""add the hook call's and the Jev check's records to Version attempts

A first Version's Draft is written to start with a Hook from the curated library, and a Feedback
Version asks Jev whether it needs a new Hook. The attempt stores the Hook's library id and text,
whether the writing call started with it, the hook call's model, usage and raw answer, and the
Jev check's top label, every label's probability and the Jev version.

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
        batch_op.add_column(sa.Column("hook_text", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("hook_followed", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("hooking_model", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "hooking_usage",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "hook_answer",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("hook_check", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "hook_check_probabilities",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("hook_check_model", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.drop_column("hook_check_model")
        batch_op.drop_column("hook_check_probabilities")
        batch_op.drop_column("hook_check")
        batch_op.drop_column("hook_answer")
        batch_op.drop_column("hooking_usage")
        batch_op.drop_column("hooking_model")
        batch_op.drop_column("hook_followed")
        batch_op.drop_column("hook_text")
        batch_op.drop_column("hook_name")
