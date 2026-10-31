"""store Top-ups and what is charged to them

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-31 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COUNT = sa.Enum("generations", "x_posts", "link_x_posts", name="allowance_count_enum")


def upgrade() -> None:
    op.create_table(
        "top_ups",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("stripe_checkout_session_id", sa.String(), nullable=False),
        sa.Column("generations", sa.Integer(), nullable=True),
        sa.Column("x_posts", sa.Integer(), nullable=True),
        sa.Column("link_x_posts", sa.Integer(), nullable=True),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("removed", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_checkout_session_id"),
    )
    op.create_index("ix_top_ups_user_id", "top_ups", ["user_id"])
    op.create_index("ix_top_ups_expires_at", "top_ups", ["expires_at"])
    op.create_table(
        "top_up_charges",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("top_up_id", sa.String(), nullable=False),
        sa.Column("count", _COUNT, nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("version_attempt_id", sa.String(), nullable=True),
        sa.Column("scheduled_post_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["top_up_id"], ["top_ups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["version_attempt_id"], ["version_attempts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["scheduled_post_id"], ["scheduled_posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_top_up_charges_top_up_id", "top_up_charges", ["top_up_id"])
    op.create_index(
        "ix_top_up_charges_version_attempt_id", "top_up_charges", ["version_attempt_id"]
    )
    op.create_index("ix_top_up_charges_scheduled_post_id", "top_up_charges", ["scheduled_post_id"])


def downgrade() -> None:
    op.drop_table("top_up_charges")
    op.drop_table("top_ups")
    _COUNT.drop(op.get_bind(), checkfirst=True)
