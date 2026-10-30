"""store each Inspiration author's photo URL beside their last fetch

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
    with op.batch_alter_table("author_fetches", schema=None) as batch_op:
        batch_op.add_column(sa.Column("photo_url", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("author_fetches", schema=None) as batch_op:
        batch_op.drop_column("photo_url")
