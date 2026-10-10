"""add Scheduled posts

A Scheduled post keeps its own copy of the text, the X account it targets, its publish
time and its state. It also has room for what later steps need: the source Version, the
429 retry count and next attempt, and when it entered publishing for crash recovery.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-10 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheduled_posts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("x_user_id", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("publish_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "scheduled", "publishing", "published", "failed", name="scheduled_post_state_enum"
            ),
            nullable=False,
        ),
        sa.Column("failed_reason", sa.Text(), nullable=True),
        sa.Column("x_post_id", sa.String(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_version_id", sa.String(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publishing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["version_attempts.id"],
            name=op.f("fk_scheduled_posts_source_version_id_version_attempts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_scheduled_posts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_posts")),
    )
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.create_index(
            "ix_scheduled_posts_state_publish_at", ["state", "publish_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_scheduled_posts_scheduled_posts_user_id"), ["user_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_scheduled_posts_scheduled_posts_user_id"))
        batch_op.drop_index("ix_scheduled_posts_state_publish_at")
    op.drop_table("scheduled_posts")
    sa.Enum(name="scheduled_post_state_enum").drop(op.get_bind(), checkfirst=True)
