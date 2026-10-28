"""link each Scheduled post to its Post, at most one per Post

Every Scheduled post is copied from a Version, and a Post goes out at most once (ADR 0015), so a
Scheduled post holds its Post's id under a unique constraint. Existing ones copied from a Version
take its Post's id; where two share a Post, only the newest keeps it.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-28 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("post_id", sa.String(), nullable=True))
    op.execute(
        "UPDATE scheduled_posts SET post_id = (SELECT v.post_id FROM version_attempts v "
        "WHERE v.id = scheduled_posts.source_version_id) "
        "WHERE scheduled_posts.id = (SELECT s.id FROM scheduled_posts s "
        "JOIN version_attempts sv ON sv.id = s.source_version_id "
        "WHERE sv.post_id = (SELECT v.post_id FROM version_attempts v "
        "WHERE v.id = scheduled_posts.source_version_id) "
        "ORDER BY s.created_at DESC, s.id DESC LIMIT 1)"
    )
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.create_foreign_key(
            batch_op.f("fk_scheduled_posts_post_id_posts"),
            "posts",
            ["post_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint(batch_op.f("uq_scheduled_posts_post_id"), ["post_id"])


def downgrade() -> None:
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("uq_scheduled_posts_post_id"), type_="unique")
        batch_op.drop_constraint(batch_op.f("fk_scheduled_posts_post_id_posts"), type_="foreignkey")
        batch_op.drop_column("post_id")
