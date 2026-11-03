"""scheduled post media

A Scheduled post's own copy of its Parts' Media references (ADR 0021), placed by Part position.

Revision ID: 0042
Revises: 0041
Create Date: 2026-11-03 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0042"
down_revision: Union[str, None] = "0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheduled_post_media",
        sa.Column("scheduled_post_id", sa.String(), nullable=False),
        sa.Column("media_id", sa.String(), nullable=False),
        sa.Column("part_position", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["media_id"],
            ["media.id"],
            name=op.f("fk_scheduled_post_media_media_id_media"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scheduled_post_id"],
            ["scheduled_posts.id"],
            name=op.f("fk_scheduled_post_media_scheduled_post_id_scheduled_posts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "scheduled_post_id", "media_id", name=op.f("pk_scheduled_post_media")
        ),
    )
    with op.batch_alter_table("scheduled_post_media", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_scheduled_post_media_scheduled_post_media_media_id"),
            ["media_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("scheduled_post_media", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_scheduled_post_media_scheduled_post_media_media_id"))
    op.drop_table("scheduled_post_media")
