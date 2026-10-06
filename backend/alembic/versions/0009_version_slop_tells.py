"""add the slop check's tells to Version attempts

A succeeded attempt stores the tells the slop check found in its Final, so a response can list
them without running the check again.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-06 22:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "slop_tells",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.drop_column("slop_tells")
