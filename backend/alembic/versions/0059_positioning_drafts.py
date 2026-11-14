"""what a Positioning draft reads and what limits it

Revision ID: 0059
Revises: 0058
Create Date: 2026-11-13 22:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0059"
down_revision: Union[str, None] = "0058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("x_connections") as batch:
        batch.add_column(sa.Column("bio", sa.Text(), nullable=True))
        batch.add_column(sa.Column("location", sa.Text(), nullable=True))
        batch.add_column(sa.Column("website", sa.Text(), nullable=True))
    op.create_table(
        "positioning_draft_requests",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_positioning_draft_requests_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_positioning_draft_requests")),
    )
    op.create_index(
        op.f("ix_positioning_draft_requests_positioning_draft_requests_user_id"),
        "positioning_draft_requests",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_positioning_draft_requests_positioning_draft_requests_user_id"),
        table_name="positioning_draft_requests",
    )
    op.drop_table("positioning_draft_requests")
    with op.batch_alter_table("x_connections") as batch:
        batch.drop_column("website")
        batch.drop_column("location")
        batch.drop_column("bio")
