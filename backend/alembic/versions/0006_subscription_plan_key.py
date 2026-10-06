"""store the Plan key of each Subscription

Pumpkit's copy of a Subscription is synced from Stripe (see
docs/adr/0004-billing-webhooks-are-nudges.md) and now keeps the price's lookup
key, the Plan key, beside the price ID. It is nullable: a price may have no
lookup key. No deployment holds real data, so nothing is back-filled.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-06 10:32:10.718202

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("plan_key", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("subscriptions", schema=None) as batch_op:
        batch_op.drop_column("plan_key")
