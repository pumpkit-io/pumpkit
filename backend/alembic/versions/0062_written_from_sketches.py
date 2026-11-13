"""a Version keeps what its sketches and merge chose

Revision ID: 0062
Revises: 0061
Create Date: 2026-11-14 03:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0062"
down_revision: Union[str, None] = "0061"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("hook_levers", _JSON, nullable=True))
        batch_op.add_column(sa.Column("hook_types", _JSON, nullable=True))
        batch_op.add_column(sa.Column("cta_type", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("sketches", _JSON, nullable=True))
        batch_op.add_column(sa.Column("merge", _JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.drop_column("merge")
        batch_op.drop_column("sketches")
        batch_op.drop_column("cta_type")
        batch_op.drop_column("hook_types")
        batch_op.drop_column("hook_levers")
