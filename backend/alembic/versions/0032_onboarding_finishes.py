"""who finished Onboarding, counting everyone already set up as finished

A User who already has an X connection and an Inspiration author has done what Onboarding asks,
so they are marked finished at migrate time and never sent through it.

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-31 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "onboarding_finishes",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_onboarding_finishes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_onboarding_finishes")),
    )
    op.execute(
        sa.text(
            "INSERT INTO onboarding_finishes (user_id, finished_at) "
            "SELECT x_connections.user_id, CURRENT_TIMESTAMP FROM x_connections "
            "WHERE EXISTS (SELECT 1 FROM inspiration_authors "
            "WHERE inspiration_authors.user_id = x_connections.user_id)"
        )
    )


def downgrade() -> None:
    op.drop_table("onboarding_finishes")
