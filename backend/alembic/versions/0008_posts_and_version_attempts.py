"""add Posts and their Version attempts

A Post keeps its Brief and the ordered ids of the author posts that made its corpus. Each
attempt at a Version is stored with its status: a succeeded one with its Draft, Final, models
and token usage, a failed one with its error.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-06 21:12:33.038873

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json() -> sa.types.TypeEngine:
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "posts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("corpus_post_ids", _json(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_posts_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_posts")),
    )
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_posts_posts_user_id"), ["user_id"], unique=False)

    op.create_table(
        "version_attempts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("post_id", sa.String(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("succeeded", "failed", name="version_attempt_status_enum"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=True),
        sa.Column("draft", sa.Text(), nullable=True),
        sa.Column("final", sa.Text(), nullable=True),
        sa.Column("final_char_count", sa.Integer(), nullable=True),
        sa.Column("writing_model", sa.String(), nullable=True),
        sa.Column("humanizing_model", sa.String(), nullable=True),
        sa.Column("writing_usage", _json(), nullable=True),
        sa.Column("humanizing_usage", _json(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["posts.id"],
            name=op.f("fk_version_attempts_post_id_posts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_version_attempts")),
        sa.UniqueConstraint("post_id", "sequence", name="uq_version_attempts_post_id_sequence"),
        sa.UniqueConstraint(
            "post_id", "version_number", name="uq_version_attempts_post_id_version_number"
        ),
    )
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_version_attempts_version_attempts_post_id"), ["post_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_version_attempts_version_attempts_post_id"))
    op.drop_table("version_attempts")
    sa.Enum(name="version_attempt_status_enum").drop(op.get_bind(), checkfirst=True)
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_posts_posts_user_id"))
    op.drop_table("posts")
