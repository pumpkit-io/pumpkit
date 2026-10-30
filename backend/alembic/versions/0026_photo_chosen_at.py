"""add the Photo chosen marker to users

Pumpkit fills a Photo on its own only while a User has neither a Photo nor the marker.
Every existing Photo was chosen, so its User gets the marker.

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-31 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("photo_chosen_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE users SET photo_chosen_at = CURRENT_TIMESTAMP WHERE avatar_data_url IS NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("photo_chosen_at")
