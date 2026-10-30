"""drop the slop check's tells from Version attempts

The slop check no longer runs on a Version's text, and nothing read the tells it stored.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-30 23:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.drop_column("slop_tells")


def downgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "slop_tells",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
                nullable=True,
            )
        )
    # The code before this migration reads every succeeded attempt's tells as a list.
    op.execute("UPDATE version_attempts SET slop_tells = '[]'")
