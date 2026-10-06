"""add Inspiration authors, fetched author posts and per-handle fetch records

A User lists up to three Inspiration authors. Their fetched posts and the time each
handle was last fetched are shared across Users, so they carry no user_id, and removing
an author from a list leaves its posts stored.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-06 21:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "author_fetches",
        sa.Column("handle", sa.String(), nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("handle", name=op.f("pk_author_fetches")),
    )
    op.create_table(
        "author_posts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("handle", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_author_posts")),
    )
    with op.batch_alter_table("author_posts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_author_posts_author_posts_handle"), ["handle"], unique=False
        )

    op.create_table(
        "inspiration_authors",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("handle", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_inspiration_authors_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inspiration_authors")),
        sa.UniqueConstraint("user_id", "handle", name=op.f("uq_inspiration_authors_user_id")),
    )
    with op.batch_alter_table("inspiration_authors", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_inspiration_authors_inspiration_authors_user_id"),
            ["user_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("inspiration_authors", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_inspiration_authors_inspiration_authors_user_id"))
    op.drop_table("inspiration_authors")
    with op.batch_alter_table("author_posts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_author_posts_author_posts_handle"))
    op.drop_table("author_posts")
    op.drop_table("author_fetches")
