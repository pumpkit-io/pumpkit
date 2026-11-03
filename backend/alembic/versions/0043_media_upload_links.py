"""media upload links

One-time links `attach_media` makes so an AI app can send a local Media file to one Part of a
Post with no other credentials, stored by the hash of their token.

Revision ID: 0043
Revises: 0042
Create Date: 2026-11-03 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "media_upload_links",
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("post_id", sa.String(), nullable=False),
        sa.Column("part_index", sa.Integer(), nullable=False),
        sa.Column("alt_text", sa.Text(), nullable=True),
        sa.Column("app_connection_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["app_connection_id"],
            ["app_connections.id"],
            name=op.f("fk_media_upload_links_app_connection_id_app_connections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["posts.id"],
            name=op.f("fk_media_upload_links_post_id_posts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_media_upload_links_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_media_upload_links")),
    )
    with op.batch_alter_table("media_upload_links", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_media_upload_links_media_upload_links_app_connection_id"),
            ["app_connection_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_media_upload_links_media_upload_links_expires_at"),
            ["expires_at"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_media_upload_links_media_upload_links_post_id"),
            ["post_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_media_upload_links_media_upload_links_user_id"),
            ["user_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("media_upload_links", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_media_upload_links_media_upload_links_user_id"))
        batch_op.drop_index(batch_op.f("ix_media_upload_links_media_upload_links_post_id"))
        batch_op.drop_index(batch_op.f("ix_media_upload_links_media_upload_links_expires_at"))
        batch_op.drop_index(
            batch_op.f("ix_media_upload_links_media_upload_links_app_connection_id")
        )
    op.drop_table("media_upload_links")
