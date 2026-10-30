"""record when a Post's next Version started being written

While Feedback's Version is written, the Post's Text takes no edit, restore or other Feedback,
since the Version replaces it. No existing Post is being written.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-30 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("writing_since", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.drop_column("writing_since")
