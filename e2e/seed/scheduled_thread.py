"""Give the seeded e2e user a Post with a two-Part Thread Version, scheduled for tomorrow.

A Scheduled post is always copied from a Version (ADR 0015), and writing one would call the
LLM, so the Post, its Version and the Scheduled post are written straight into the database.
Run it like `seed_user.py`, after it and `connect_x.py`.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import pumpkit.scheduling.service as scheduled_posts_service
from pumpkit.auth.models import User
from pumpkit.core.db.session import _db_session_handler
from pumpkit.posts.models import ATTEMPT_SUCCEEDED, Post, VersionAttempt

E2E_EMAIL = "e2e@e2e-user.dev"
PARTS = ["E2E Thread, Part one.", "E2E Thread, Part two."]


async def main() -> None:
    now = datetime.now(timezone.utc)
    async with _db_session_handler.async_session_maker() as db:
        user = (await db.execute(select(User).where(User.email == E2E_EMAIL))).scalar_one()
        post = Post(user_id=user.id, brief="E2E Thread", corpus_post_ids=[], created_at=now)
        version = VersionAttempt(
            post=post,
            sequence=1,
            format="thread",
            status=ATTEMPT_SUCCEEDED,
            version_number=1,
            sketch_parts=PARTS,
            parts=PARTS,
            slop_tells=[],
            created_at=now,
        )
        db.add_all([post, version])
        await db.flush()
        await scheduled_posts_service.create(
            db,
            user_id=user.id,
            x_user_id="e2e-x-user",
            post_id=post.id,
            source_version_id=version.id,
            parts=PARTS,
            publish_at=(now + timedelta(days=1)).replace(second=0, microsecond=0),
            now=now,
        )
        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
