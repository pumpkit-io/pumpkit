"""store a Scheduled post's text as Parts

A Scheduled post holds an ordered list of Parts, each with its text and, once X accepts it, its
X post id. Each existing Scheduled post becomes one Part with its text, keeping its X post id
when Published.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-25 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# A one-Part Scheduled post's Part reuses its ULID: "scheduled_post_" is 15 characters.
_PART_ID = "'scheduled_post_part_' || substr(id, 16)"


def upgrade() -> None:
    op.create_table(
        "scheduled_post_parts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("scheduled_post_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("x_post_id", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["scheduled_post_id"],
            ["scheduled_posts.id"],
            name=op.f("fk_scheduled_post_parts_scheduled_post_id_scheduled_posts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_post_parts")),
        sa.UniqueConstraint(
            "scheduled_post_id",
            "position",
            name=op.f("uq_scheduled_post_parts_scheduled_post_id"),
        ),
    )
    op.execute(
        "INSERT INTO scheduled_post_parts (id, scheduled_post_id, position, text, x_post_id) "
        f"SELECT {_PART_ID}, id, 0, text, x_post_id FROM scheduled_posts"
    )
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.drop_column("x_post_id")
        batch_op.drop_column("text")


def downgrade() -> None:
    # A Thread keeps only its first Part.
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("text", sa.Text(), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("x_post_id", sa.String(), nullable=True))
    op.execute(
        "UPDATE scheduled_posts SET "
        "text = (SELECT text FROM scheduled_post_parts p "
        "WHERE p.scheduled_post_id = scheduled_posts.id AND p.position = 0), "
        "x_post_id = (SELECT x_post_id FROM scheduled_post_parts p "
        "WHERE p.scheduled_post_id = scheduled_posts.id AND p.position = 0)"
    )
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.alter_column("text", server_default=None)
    op.drop_table("scheduled_post_parts")
