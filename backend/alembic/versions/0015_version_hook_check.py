"""add the Jev check's label, probabilities and model to Version attempts

A Feedback Version asks Jev whether its opening needs a new Hook. Its attempt stores the top
label, every label's probability and the Jev version that answered. All three stay null when
Jev wasn't asked (the first Version) or didn't answer.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-20 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
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
