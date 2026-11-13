"""a Post belongs to an Idea of a Brief

Revision ID: 0059
Revises: 0058
Create Date: 2026-11-13 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from ulid import ULID

from alembic import op

revision: str = "0059"
down_revision: Union[str, None] = "0058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

_briefs = sa.table(
    "briefs",
    sa.column("id", sa.String()),
    sa.column("user_id", sa.String()),
    sa.column("text", sa.Text()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)
_ideas = sa.table(
    "ideas",
    sa.column("id", sa.String()),
    sa.column("brief_id", sa.String()),
    sa.column("posting_order", sa.Integer()),
)
_posts = sa.table(
    "posts",
    sa.column("id", sa.String()),
    sa.column("user_id", sa.String()),
    sa.column("idea_id", sa.String()),
    sa.column("brief", sa.Text()),
    sa.column("corpus_post_ids", _JSON),
    sa.column("created_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    op.create_table(
        "briefs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_briefs_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_briefs")),
    )
    op.create_index(op.f("ix_briefs_briefs_user_id"), "briefs", ["user_id"], unique=False)
    op.create_table(
        "ideas",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("brief_id", sa.String(), nullable=False),
        sa.Column("posting_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["brief_id"], ["briefs.id"], name=op.f("fk_ideas_brief_id_briefs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ideas")),
    )
    op.create_index(op.f("ix_ideas_ideas_brief_id"), "ideas", ["brief_id"], unique=False)
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("idea_id", sa.String(), nullable=True))
        batch_op.alter_column("corpus_post_ids", existing_type=_JSON, nullable=True)

    bind = op.get_bind()
    posts = bind.execute(
        sa.select(_posts.c.id, _posts.c.user_id, _posts.c.brief, _posts.c.created_at)
    ).all()
    for post_id, user_id, brief, created_at in posts:
        brief_id, idea_id = f"brief_{ULID()}", f"idea_{ULID()}"
        bind.execute(
            _briefs.insert().values(id=brief_id, user_id=user_id, text=brief, created_at=created_at)
        )
        bind.execute(_ideas.insert().values(id=idea_id, brief_id=brief_id, posting_order=1))
        bind.execute(_posts.update().where(_posts.c.id == post_id).values(idea_id=idea_id))

    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.alter_column("idea_id", existing_type=sa.String(), nullable=False)
        batch_op.create_foreign_key(
            batch_op.f("fk_posts_idea_id_ideas"), "ideas", ["idea_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_unique_constraint(batch_op.f("uq_posts_idea_id"), ["idea_id"])
        batch_op.drop_column("brief")


def downgrade() -> None:
    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("brief", sa.Text(), nullable=True))

    text_of_post = (
        sa.select(_briefs.c.text)
        .join(_ideas, _ideas.c.brief_id == _briefs.c.id)
        .where(_ideas.c.id == _posts.c.idea_id)
        .scalar_subquery()
    )
    bind = op.get_bind()
    bind.execute(_posts.update().values(brief=text_of_post))
    bind.execute(
        _posts.update().where(_posts.c.corpus_post_ids.is_(sa.null())).values(corpus_post_ids=[])
    )

    with op.batch_alter_table("posts", schema=None) as batch_op:
        batch_op.alter_column("brief", existing_type=sa.Text(), nullable=False)
        batch_op.alter_column("corpus_post_ids", existing_type=_JSON, nullable=False)
        batch_op.drop_constraint(batch_op.f("uq_posts_idea_id"), type_="unique")
        batch_op.drop_constraint(batch_op.f("fk_posts_idea_id_ideas"), type_="foreignkey")
        batch_op.drop_column("idea_id")
    op.drop_index(op.f("ix_ideas_ideas_brief_id"), table_name="ideas")
    op.drop_table("ideas")
    op.drop_index(op.f("ix_briefs_briefs_user_id"), table_name="briefs")
    op.drop_table("briefs")
