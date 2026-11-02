"""at most one unrevoked connection per User and app

Two approvals racing for the same app could each find no connection and both insert one. A
partial unique index on `app_connections` over unrevoked rows refuses the second, so a User
keeps one Connected app per app.

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-01 21:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX = "uq_app_connections_user_id_client_id_unrevoked"


def upgrade() -> None:
    op.create_index(
        _INDEX,
        "app_connections",
        ["user_id", "client_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="app_connections")
