"""store the X account's photo with the X connection

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-30 23:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("x_connections", schema=None) as batch_op:
        batch_op.add_column(sa.Column("photo_url", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("x_connections", schema=None) as batch_op:
        batch_op.drop_column("photo_url")
