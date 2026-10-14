"""add a Community to Scheduled posts

A Scheduled post may go to one Community instead of the User's profile. It keeps the
Community's ID, its name as shown when it was picked (empty when it couldn't be looked up), and
whether X also shares it with the account's followers. Existing Scheduled posts are profile posts.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-14 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("community_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("community_name", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "share_with_followers",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("scheduled_posts", schema=None) as batch_op:
        batch_op.drop_column("share_with_followers")
        batch_op.drop_column("community_name")
        batch_op.drop_column("community_id")
