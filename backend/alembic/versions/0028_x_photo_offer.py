"""record when the User answered the offer to use the X account's photo

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-31 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("x_connections", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("photo_offer_answered_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("x_connections", schema=None) as batch_op:
        batch_op.drop_column("photo_offer_answered_at")
