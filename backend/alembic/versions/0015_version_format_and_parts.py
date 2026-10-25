"""store each Version attempt's Format, and its Draft and Final as Parts

A Version is a single X post or a Thread, so its Draft and Final become ordered lists of Part
texts. Every existing attempt becomes a single X post, its text the only Part. The Final's count
is no longer stored: a response counts each Part the way its Format's limit does.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-25 12:00:00.000000

"""

from typing import Optional, Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FORMAT = sa.Enum("post", "thread", name="version_format_enum")
_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _attempts(*columns: sa.Column) -> sa.TableClause:
    return sa.table("version_attempts", sa.column("id", sa.String()), *columns)


def _parts(text: Optional[str]) -> Optional[list[str]]:
    return None if text is None else [text]


def upgrade() -> None:
    _FORMAT.create(op.get_bind(), checkfirst=True)
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("format", _FORMAT, nullable=True))
        batch_op.add_column(sa.Column("draft_parts", _JSON, nullable=True))
        batch_op.add_column(sa.Column("final_parts", _JSON, nullable=True))

    old = _attempts(sa.column("draft", sa.Text()), sa.column("final", sa.Text()))
    new = _attempts(
        sa.column("format", _FORMAT),
        sa.column("draft_parts", _JSON),
        sa.column("final_parts", _JSON),
    )
    bind = op.get_bind()
    for id_, draft, final in bind.execute(sa.select(old.c.id, old.c.draft, old.c.final)).all():
        bind.execute(
            new.update()
            .where(new.c.id == id_)
            .values(format="post", draft_parts=_parts(draft), final_parts=_parts(final))
        )

    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.alter_column("format", existing_type=_FORMAT, nullable=False)
        batch_op.drop_column("final_char_count")
        batch_op.drop_column("final")
        batch_op.drop_column("draft")


def downgrade() -> None:
    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("draft", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("final", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("final_char_count", sa.Integer(), nullable=True))

    new = _attempts(
        sa.column("draft", sa.Text()),
        sa.column("final", sa.Text()),
        sa.column("final_char_count", sa.Integer()),
    )
    old = _attempts(sa.column("draft_parts", _JSON), sa.column("final_parts", _JSON))
    bind = op.get_bind()
    rows = bind.execute(sa.select(old.c.id, old.c.draft_parts, old.c.final_parts)).all()
    for id_, draft_parts, final_parts in rows:
        # A Thread had no single text before, so its Parts join with blank lines.
        draft = None if draft_parts is None else "\n\n".join(draft_parts)
        final = None if final_parts is None else "\n\n".join(final_parts)
        bind.execute(
            new.update()
            .where(new.c.id == id_)
            .values(
                draft=draft, final=final, final_char_count=None if final is None else len(final)
            )
        )

    with op.batch_alter_table("version_attempts", schema=None) as batch_op:
        batch_op.drop_column("final_parts")
        batch_op.drop_column("draft_parts")
        batch_op.drop_column("format")
    _FORMAT.drop(op.get_bind(), checkfirst=True)
