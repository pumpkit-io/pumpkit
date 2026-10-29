"""every Scheduled post has its Version and Post; a Version's text is its parts

A Scheduled post is always copied from a Version (ADR 0015), so its Post and Version are
required, and it goes with its Version. Any left from before that rule are deleted. A Version's
`final_parts` is renamed `parts`; no Version data changes.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-28 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SOURCE_FK = "fk_scheduled_posts_source_version_id_version_attempts"


def upgrade() -> None:
    op.execute("DELETE FROM scheduled_posts WHERE post_id IS NULL OR source_version_id IS NULL")
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.alter_column("post_id", existing_type=sa.String(), nullable=False)
        batch_op.alter_column("source_version_id", existing_type=sa.String(), nullable=False)
        batch_op.drop_constraint(batch_op.f(_SOURCE_FK), type_="foreignkey")
        batch_op.create_foreign_key(
            batch_op.f(_SOURCE_FK),
            "version_attempts",
            ["source_version_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.alter_column("version_attempts", "final_parts", new_column_name="parts")


def downgrade() -> None:
    op.alter_column("version_attempts", "parts", new_column_name="final_parts")
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_SOURCE_FK), type_="foreignkey")
        batch_op.create_foreign_key(
            batch_op.f(_SOURCE_FK),
            "version_attempts",
            ["source_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.alter_column("source_version_id", existing_type=sa.String(), nullable=True)
        batch_op.alter_column("post_id", existing_type=sa.String(), nullable=True)
