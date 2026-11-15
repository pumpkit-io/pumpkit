"""the Positioning draft each User has, kept on the server until they save a Positioning

Revision ID: 0068
Revises: 0067
Create Date: 2026-11-15 19:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0068"
down_revision: Union[str, None] = "0067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

draft_state_enum = sa.Enum("running", "ready", "failed", name="positioning_draft_state_enum")


def upgrade() -> None:
    op.create_table(
        "positioning_drafts",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("state", draft_state_enum, nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_positioning_drafts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_positioning_drafts")),
    )


def downgrade() -> None:
    op.drop_table("positioning_drafts")
    draft_state_enum.drop(op.get_bind(), checkfirst=True)
