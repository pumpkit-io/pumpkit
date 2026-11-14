"""Using Generations up before a test, by storing written Posts directly."""

from datetime import datetime, timezone

from pumpkit.posts.models import Post, VersionAttempt


async def use_a_generation(db, user_id: str) -> None:
    """Store a Post written in the month, which counts against the User's Generations."""
    moment = datetime(2026, 10, 2, tzinfo=timezone.utc)
    post = Post(user_id=user_id, brief="earlier", corpus_post_ids=[], created_at=moment)
    db.add(post)
    await db.flush()
    db.add(
        VersionAttempt(
            user_id=user_id,
            post_id=post.id,
            sequence=1,
            version_number=1,
            format="post",
            status="succeeded",
            parts=["earlier"],
            created_at=moment,
        )
    )
    await db.commit()
