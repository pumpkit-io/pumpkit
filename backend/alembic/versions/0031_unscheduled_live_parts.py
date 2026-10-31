"""keep the live Parts of deleted Scheduled posts counting as X posts

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-31 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "unscheduled_live_parts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("publish_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("x_posts", sa.Integer(), nullable=False),
        sa.Column("link_x_posts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_unscheduled_live_parts_user_id_publish_at",
        "unscheduled_live_parts",
        ["user_id", "publish_at"],
    )


def downgrade() -> None:
    op.drop_table("unscheduled_live_parts")
