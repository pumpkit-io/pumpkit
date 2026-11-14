"""a version attempt names its User and outlives a discarded Post, so its Generation stays used

Revision ID: 0066
Revises: 0065
Create Date: 2026-11-15 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0066"
down_revision: Union[str, None] = "0065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_POST_FK = "fk_version_attempts_post_id_posts"
_USER_FK = "fk_version_attempts_user_id_users"
_USER_INDEX = "ix_version_attempts_version_attempts_user_id"


def upgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(), nullable=True))
    op.execute(
        "UPDATE version_attempts SET user_id = "
        "(SELECT posts.user_id FROM posts WHERE posts.id = version_attempts.post_id)"
    )
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.alter_column("user_id", existing_type=sa.String(), nullable=False)
        batch_op.create_foreign_key(
            batch_op.f(_USER_FK), "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_index(batch_op.f(_USER_INDEX), ["user_id"], unique=False)
        batch_op.alter_column("post_id", existing_type=sa.String(), nullable=True)
        batch_op.drop_constraint(batch_op.f(_POST_FK), type_="foreignkey")
        batch_op.create_foreign_key(
            batch_op.f(_POST_FK), "posts", ["post_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    # A discarded Post's attempts have no Post to go back to.
    op.execute("DELETE FROM version_attempts WHERE post_id IS NULL")
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f(_POST_FK), type_="foreignkey")
        batch_op.create_foreign_key(
            batch_op.f(_POST_FK), "posts", ["post_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.alter_column("post_id", existing_type=sa.String(), nullable=False)
        batch_op.drop_index(batch_op.f(_USER_INDEX))
        batch_op.drop_constraint(batch_op.f(_USER_FK), type_="foreignkey")
        batch_op.drop_column("user_id")
