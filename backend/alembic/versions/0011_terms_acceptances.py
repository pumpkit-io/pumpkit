"""add Terms acceptances

A User accepts the Terms before each checkout (ADR 0010). Each row records the Terms version,
when it was accepted and the three boxes the User ticked, and goes with the User's account.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-11 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "terms_acceptances",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("terms_version", sa.String(), nullable=False),
        sa.Column(
            "accepted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("accepted_terms", sa.Boolean(), nullable=False),
        sa.Column("requested_immediate_start", sa.Boolean(), nullable=False),
        sa.Column("approved_specific_clauses", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_terms_acceptances_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terms_acceptances")),
    )
    with op.batch_alter_table("terms_acceptances", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_terms_acceptances_terms_acceptances_user_id"), ["user_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("terms_acceptances", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_terms_acceptances_terms_acceptances_user_id"))
    op.drop_table("terms_acceptances")
