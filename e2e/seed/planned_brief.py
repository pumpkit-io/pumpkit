"""Give the seeded e2e user a Positioning and a planned Brief of three separate Ideas.

The plan call and writing a Post would call the LLM, so the Brief, its Ideas and, later, its
Posts are written straight into the database. Run it like `seed_user.py`, after it:

- `planned_brief.py plan` stores the Brief and prints `BRIEF_ID=<id>`.
- `planned_brief.py ideas <brief_id>` prints the split Ideas' ids in posting order.
- `planned_brief.py writing <brief_id> <idea_id>...` starts a Post of each Idea, being written.
- `planned_brief.py written <brief_id>` writes the first Version of each Post being written.
- `planned_brief.py clean` deletes the user's Briefs and Positioning again.
"""

import asyncio
import sys
from datetime import datetime, timezone

from sqlalchemy import delete, select

from pumpkit.auth.models import User
from pumpkit.core.db.session import _db_session_handler
from pumpkit.positioning.models import Positioning
from pumpkit.posts.models import ATTEMPT_SUCCEEDED, Brief, Idea, Post, VersionAttempt
from pumpkit.posts.plans import Plan
from pumpkit.posts.service import set_text_from_version
from tests.browser_seed import x_id_for

E2E_EMAIL = "e2e@e2e-user.dev"
BRIEF = "Three things my failed SaaS taught me: the pain, the price and the integrations."
CORE_IDEAS = [
    "Make sure the pain is real before you build",
    "Charge at least 20 euros a month",
    "Don't make OAuth integrations your core value",
]


def _plan(core_idea: str) -> Plan:
    return Plan(
        core_idea=core_idea,
        takeaway="Learn it before you build.",
        reasoning="Seeded for the e2e run.",
        funnel="middle",
        desired_action="bookmark",
        format="post",
        length="short",
        structure="few_lines",
    )


async def main(command: str, args: list[str]) -> None:
    now = datetime.now(timezone.utc)
    async with _db_session_handler.async_session_maker() as db:
        user = (
            await db.execute(select(User).where(User.x_user_id == x_id_for(E2E_EMAIL)))
        ).scalar_one()
        if command == "clean":
            await db.execute(delete(Brief).where(Brief.user_id == user.id))
            await db.execute(delete(Positioning).where(Positioning.user_id == user.id))
        elif command == "plan":
            await db.execute(delete(Positioning).where(Positioning.user_id == user.id))
            db.add(Positioning(user_id=user.id, text="I post about bootstrapping.", saved_at=now))
            brief = Brief(
                user_id=user.id,
                text=BRIEF,
                created_at=now,
                positioning="I post about bootstrapping.",
                planning_reasoning="Three separate lessons.",
                ideas=[
                    Idea(posting_order=1, whole_brief=True, plan=_plan("Three lessons")),
                    *(
                        Idea(posting_order=order, whole_brief=False, plan=_plan(core_idea))
                        for order, core_idea in enumerate(CORE_IDEAS, start=1)
                    ),
                ],
            )
            db.add(brief)
            await db.flush()
            print(f"BRIEF_ID={brief.id}")
        elif command == "ideas":
            [brief_id] = args
            ideas = await db.scalars(
                select(Idea)
                .where(Idea.brief_id == brief_id, Idea.whole_brief.is_(False))
                .order_by(Idea.posting_order)
            )
            print(" ".join(idea.id for idea in ideas))
        elif command == "writing":
            brief_id, *idea_ids = args
            ideas = await db.scalars(
                select(Idea).where(Idea.brief_id == brief_id, Idea.id.in_(idea_ids))
            )
            for idea in ideas:
                db.add(
                    Post(
                        user_id=user.id, idea=idea, created_at=now, writing_since=now, text_media=[]
                    )
                )
        elif command == "written":
            [brief_id] = args
            posts = await db.scalars(
                select(Post)
                .join(Idea, Post.idea_id == Idea.id)
                .where(Idea.brief_id == brief_id, Post.writing_since.is_not(None))
            )
            for post in posts:
                parts = [f"Written: {post.idea.core_idea}."]
                version = VersionAttempt(
                    post=post,
                    sequence=1,
                    format="post",
                    status=ATTEMPT_SUCCEEDED,
                    version_number=1,
                    sketch_parts=parts,
                    parts=parts,
                    first_reply=False,
                    created_at=now,
                )
                db.add(version)
                set_text_from_version(post, version)
                post.writing_since = None
        else:
            raise SystemExit(f"Unknown command {command}")
        await db.commit()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2:]))
