"""a Post keeps the Feedback being written, to show it once its write fails

Revision ID: 0064
Revises: 0063
Create Date: 2026-11-15 06:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0064"
down_revision: Union[str, None] = "0063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The Versions' Format type, which already exists.
_FORMAT = sa.Enum("post", "thread", name="version_format_enum").with_variant(
    postgresql.ENUM("post", "thread", name="version_format_enum", create_type=False),
    "postgresql",
)


def upgrade() -> None:
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("unwritten_feedback", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("unwritten_feedback_format", _FORMAT, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.drop_column("unwritten_feedback_format")
        batch_op.drop_column("unwritten_feedback")
