"""give each Version from Feedback room for its Starting text

The Post's Text a Feedback was given on is kept with the Version it made when it differs from the
Version before (ADR 0016): its Format, its Parts and the number of the Version it came from. Every
existing Version keeps none, since each was written from the Version before it.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-30 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The Versions' Format type, which already exists.
_FORMAT = sa.Enum("post", "thread", name="version_format_enum").with_variant(
    postgresql.ENUM("post", "thread", name="version_format_enum", create_type=False),
    "postgresql",
)
_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("starting_text_format", _FORMAT, nullable=True))
        batch_op.add_column(sa.Column("starting_text_parts", _JSON, nullable=True))
        batch_op.add_column(sa.Column("starting_text_version_number", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.drop_column("starting_text_version_number")
        batch_op.drop_column("starting_text_parts")
        batch_op.drop_column("starting_text_format")
