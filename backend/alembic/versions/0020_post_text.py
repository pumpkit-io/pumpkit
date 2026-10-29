"""give each Post its Text, set from its latest Version

A Post has one Text (ADR 0016): its Format, its Parts, the number of the Version it came from,
and whether it was edited since. Every existing Post's Text becomes its latest Version, not
edited; a Post with no Version keeps none.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-30 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The Versions' Format type, which already exists.
_FORMAT = sa.Enum("post", "thread", name="version_format_enum").with_variant(
    postgresql.ENUM("post", "thread", name="version_format_enum", create_type=False),
    "postgresql",
)
_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("text_format", _FORMAT, nullable=True))
        batch_op.add_column(sa.Column("text_parts", _JSON, nullable=True))
        batch_op.add_column(sa.Column("text_version_number", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("text_edited", sa.Boolean(), server_default=sa.false(), nullable=False)
        )

    attempts = sa.table(
        "version_attempts",
        sa.column("post_id", sa.String()),
        sa.column("status", sa.String()),
        sa.column("version_number", sa.Integer()),
        sa.column("format", _FORMAT),
        sa.column("parts", _JSON),
    )
    posts = sa.table(
        "posts",
        sa.column("id", sa.String()),
        sa.column("text_format", _FORMAT),
        sa.column("text_parts", _JSON),
        sa.column("text_version_number", sa.Integer()),
    )
    bind = op.get_bind()
    versions = bind.execute(
        sa.select(
            attempts.c.post_id, attempts.c.version_number, attempts.c.format, attempts.c.parts
        )
        .where(attempts.c.status == "succeeded")
        .order_by(attempts.c.post_id, attempts.c.version_number)
    ).all()
    # Ordered by number, so each Post's latest Version is the last one kept.
    latest = {post_id: (number, format, parts) for post_id, number, format, parts in versions}
    for post_id, (number, format, parts) in latest.items():
        bind.execute(
            posts.update()
            .where(posts.c.id == post_id)
            .values(text_format=format, text_parts=parts, text_version_number=number)
        )


def downgrade() -> None:
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.drop_column("text_edited")
        batch_op.drop_column("text_version_number")
        batch_op.drop_column("text_parts")
        batch_op.drop_column("text_format")
