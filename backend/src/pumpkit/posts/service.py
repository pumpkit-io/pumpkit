from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pumpkit.authors.models import AuthorPost, InspirationAuthor
from pumpkit.core.errors import ConflictError
from pumpkit.core.time import as_utc
from pumpkit.posts.formats import Format
from pumpkit.posts.models import (
    ATTEMPT_FAILED,
    ATTEMPT_SUCCEEDED,
    Post,
    VersionAttempt,
)
from pumpkit.posts.writing import slop
from pumpkit.posts.writing.constants import CORPUS_POSTS_PER_AUTHOR
from pumpkit.posts.writing.corpus import Corpus, CorpusPost, group_corpus
from pumpkit.posts.writing.versions import WrittenVersion


async def corpus_for_user(db: AsyncSession, *, user_id: str) -> Corpus:
    """
    The newest stored posts of each of the User's Inspiration authors, in list order.
    Ties on the posting time go to the higher post id, as in pumpkit-v6, so a corpus is stable.
    """
    handles = (
        await db.execute(
            select(InspirationAuthor.handle)
            .where(InspirationAuthor.user_id == user_id)
            .order_by(InspirationAuthor.position)
        )
    ).scalars()
    posts: list[CorpusPost] = []
    for handle in list(handles):
        rows = await db.execute(
            select(AuthorPost.id, AuthorPost.text)
            .where(AuthorPost.handle == handle)
            .order_by(AuthorPost.posted_at.desc(), AuthorPost.id.desc())
            .limit(CORPUS_POSTS_PER_AUTHOR)
        )
        posts.extend(CorpusPost(post_id=id_, handle=handle, text=text) for id_, text in rows.all())
    return group_corpus(posts)


async def get_user_post(db: AsyncSession, *, user_id: str, post_id: str) -> Optional[Post]:
    """The User's Post with its attempts in order, or None when it isn't theirs."""
    result = await db.execute(
        select(Post)
        .where(Post.id == post_id, Post.user_id == user_id)
        .options(selectinload(Post.attempts))
    )
    return result.scalar_one_or_none()


async def corpus_for_post(db: AsyncSession, *, post: Post) -> Corpus:
    """The corpus the Post started with, whatever the User's Inspiration authors are now."""
    rows = await db.execute(
        select(AuthorPost.id, AuthorPost.handle, AuthorPost.text).where(
            AuthorPost.id.in_(post.corpus_post_ids)
        )
    )
    by_id = {id_: CorpusPost(post_id=id_, handle=handle, text=text) for id_, handle, text in rows}
    return group_corpus([by_id[post_id] for post_id in post.corpus_post_ids])


async def attempt_times_since(db: AsyncSession, *, user_id: str, since: datetime) -> list[datetime]:
    """When the User attempted a Version after `since`, failed attempts included."""
    rows = await db.execute(
        select(VersionAttempt.created_at)
        .join(Post, VersionAttempt.post_id == Post.id)
        .where(Post.user_id == user_id, VersionAttempt.created_at > since)
    )
    return [as_utc(created_at) for created_at in rows.scalars()]


async def create_post(
    db: AsyncSession, *, user_id: str, brief: str, corpus: Corpus, now: datetime
) -> Post:
    """Flushes."""
    post = Post(user_id=user_id, brief=brief, corpus_post_ids=list(corpus.post_ids), created_at=now)
    db.add(post)
    await db.flush()
    return post


async def record_version(
    db: AsyncSession,
    *,
    post: Post,
    sequence: int,
    version_number: int,
    feedback: Optional[str],
    written: WrittenVersion,
    now: datetime,
) -> VersionAttempt:
    """Store a succeeded attempt, a Version, and make it the Post's Text. Flushes."""
    attempt = VersionAttempt(
        post_id=post.id,
        sequence=sequence,
        feedback=feedback,
        format=written.format,
        status=ATTEMPT_SUCCEEDED,
        version_number=version_number,
        sketch_parts=written.sketch_parts,
        parts=written.parts,
        sketch_model=written.sketch_model,
        humanizing_model=written.humanizing_model,
        sketch_usage=written.sketch_usage,
        humanizing_usage=written.humanizing_usage,
        hook_reasoning=written.hook.reasoning,
        hook_name=written.hook.name,
        slop_tells=[
            {"name": name, "description": description}
            for name, description in slop.find_in_parts(written.parts)
        ],
        created_at=now,
    )
    db.add(attempt)
    set_text_from_version(post, attempt)
    await db.flush()
    return attempt


def set_text_from_version(post: Post, version: VersionAttempt) -> None:
    """Make the Version the Post's Text, as written. Not flushed."""
    post.text_format = version.format
    post.text_parts = list(version.parts or [])
    post.text_version_number = version.version_number
    post.text_edited = False


class TextShapeKept(ConflictError):
    pass


def edit_text(post: Post, parts: list[str]) -> None:
    """
    Replace the Text's Parts with the User's, as typed. The Format and the number of Parts stay,
    since only Feedback changes them, and the Text reads as edited while it differs from its
    Version. Not flushed.
    """
    current = post.text_parts
    if current is None:
        raise ConflictError("This Post has no Text to edit. Start a new Post.")
    if len(parts) != len(current):
        raise TextShapeKept(
            f"Editing keeps the Text's {len(current)} Parts. Give Feedback to change its shape."
            if len(current) > 1
            else "Editing keeps the Text a single post. Give Feedback to make it a Thread."
        )
    version = next((a for a in post.attempts if a.version_number == post.text_version_number), None)
    post.text_parts = list(parts)
    post.text_edited = version is None or version.parts != parts


async def record_failed_attempt(
    db: AsyncSession,
    *,
    post: Post,
    sequence: int,
    feedback: Optional[str],
    format: Format,
    error: str,
    now: datetime,
) -> VersionAttempt:
    """Flushes."""
    attempt = VersionAttempt(
        post_id=post.id,
        sequence=sequence,
        feedback=feedback,
        format=format,
        status=ATTEMPT_FAILED,
        error=error,
        created_at=now,
    )
    db.add(attempt)
    await db.flush()
    return attempt
