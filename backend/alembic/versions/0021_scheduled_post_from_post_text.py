"""a Scheduled post no longer links to a source Version

A Scheduled post is copied from its Post's Text, not from a Version (ADR 0016, amending ADR
0015), so the link to the Version it came from goes. Every Scheduled post stays as it is. Going
down links each one to its Post's latest Version, the closest to what it was copied from.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-30 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SOURCE_FK = "fk_scheduled_posts_source_version_id_version_attempts"


def upgrade() -> None:
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_SOURCE_FK), type_="foreignkey")
        batch_op.drop_column("source_version_id")


def downgrade() -> None:
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source_version_id", sa.String(), nullable=True))
    op.execute(
        """
        UPDATE scheduled_posts SET source_version_id = (
            SELECT version_attempts.id FROM version_attempts
            WHERE version_attempts.post_id = scheduled_posts.post_id
            AND version_attempts.status = 'succeeded'
            ORDER BY version_attempts.version_number DESC
            LIMIT 1
        )
        """
    )
    # A Post with no Version can't have had a Scheduled post, but 0019 requires the link.
    op.execute("DELETE FROM scheduled_posts WHERE source_version_id IS NULL")
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.alter_column("source_version_id", existing_type=sa.String(), nullable=False)
        batch_op.create_foreign_key(
            batch_op.f(_SOURCE_FK),
            "version_attempts",
            ["source_version_id"],
            ["id"],
            ondelete="CASCADE",
        )
