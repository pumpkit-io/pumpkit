"""store the Plan key and Stripe's creation time of each Subscription

The Plan key is the price's lookup key, nullable because a price may have none.
Rows synced in one transaction share `created_at`, so Stripe's creation time
orders a User's Subscriptions. No deployment holds real data, so nothing is back-filled.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-06 10:32:10.718202

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("plan_key", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("stripe_created_at", sa.DateTime(timezone=True), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.drop_column("stripe_created_at")
        batch_op.drop_column("plan_key")
