"""media

Media a User attaches to a Post's Text (ADR 0021): one `media` row per file, and `text_media`
placing each on a Part of the Text, in order. The files themselves live in the FileStorage.

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-03 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

media_kind_enum = sa.Enum("image", "gif", "video", name="media_kind_enum")


def upgrade() -> None:
    op.create_table(
        "media",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("kind", media_kind_enum, nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("alt_text", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("file_key", sa.String(), nullable=True),
        sa.Column("preview_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_media_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media")),
    )
    with op.batch_alter_table("media", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_media_media_user_id"), ["user_id"], unique=False)

    op.create_table(
        "text_media",
        sa.Column("media_id", sa.String(), nullable=False),
        sa.Column("post_id", sa.String(), nullable=False),
        sa.Column("part_index", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["media_id"],
            ["media.id"],
            name=op.f("fk_text_media_media_id_media"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["post_id"], ["posts.id"], name=op.f("fk_text_media_post_id_posts"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("media_id", name=op.f("pk_text_media")),
    )
    with op.batch_alter_table("text_media", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_text_media_text_media_post_id"), ["post_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("text_media", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_text_media_text_media_post_id"))
    op.drop_table("text_media")
    with op.batch_alter_table("media", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_media_media_user_id"))
    op.drop_table("media")
    media_kind_enum.drop(op.get_bind(), checkfirst=True)
