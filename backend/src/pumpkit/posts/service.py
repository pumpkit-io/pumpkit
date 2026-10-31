from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pumpkit.authors.models import AuthorPost, InspirationAuthor
from pumpkit.billing.models import TopUpCharge
from pumpkit.core.errors import ConflictError
from pumpkit.core.time import as_utc
from pumpkit.posts.formats import Format
from pumpkit.posts.models import (
    ATTEMPT_FAILED,
    ATTEMPT_SUCCEEDED,
    Post,
    VersionAttempt,
)
from pumpkit.posts.writing.constants import CORPUS_POSTS_PER_AUTHOR
from pumpkit.posts.writing.corpus import Corpus, CorpusPost, group_corpus
from pumpkit.posts.writing.starting_text import StartingText
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


async def get_user_post(
    db: AsyncSession, *, user_id: str, post_id: str, for_update: bool = False
) -> Optional[Post]:
    """
    The User's Post with its attempts in order, or None when it isn't theirs. `for_update` locks
    the Post's row until the transaction ends, for a change to its Text.
    """
    query = (
        select(Post)
        .where(Post.id == post_id, Post.user_id == user_id)
        .options(selectinload(Post.attempts))
    )
    if for_update:
        query = query.with_for_update(of=Post)
    result = await db.execute(query)
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


async def count_versions_between(
    db: AsyncSession, *, user_id: str, start: datetime, end: datetime
) -> int:
    """
    The Generations of the User's Allowance used in `[start, end)`: succeeded attempts only, less
    those charged to a Top-up.
    """
    result = await db.execute(
        select(func.count())
        .select_from(VersionAttempt)
        .join(Post, VersionAttempt.post_id == Post.id)
        .where(
            Post.user_id == user_id,
            VersionAttempt.status == ATTEMPT_SUCCEEDED,
            VersionAttempt.created_at >= start,
            VersionAttempt.created_at < end,
            ~exists().where(TopUpCharge.version_attempt_id == VersionAttempt.id),
        )
    )
    return result.scalar_one()


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
    starting_text: Optional[StartingText] = None,
) -> VersionAttempt:
    """Store a succeeded attempt, a Version, and make it the Post's Text, free to change. Flushes."""
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
        starting_text_format=starting_text.format if starting_text else None,
        starting_text_parts=list(starting_text.parts) if starting_text else None,
        starting_text_version_number=starting_text.version_number if starting_text else None,
        created_at=now,
    )
    db.add(attempt)
    set_text_from_version(post, attempt)
    post.writing_since = None
    await db.flush()
    return attempt


def set_text_from_version(post: Post, version: VersionAttempt) -> None:
    """Make the Version the Post's Text, as written. Not flushed."""
    post.text_format = version.format
    post.text_parts = list(version.parts or [])
    post.text_version_number = version.version_number
    post.text_edited = False


# Longer than both model calls can take, so only a write whose request died holds the Text past it.
WRITING_TIMEOUT = timedelta(minutes=30)


class VersionBeingWritten(ConflictError):
    pass


def check_not_writing(post: Post, *, now: datetime) -> None:
    """
    Refuses while Feedback's Version is being written, since the Version replaces the Text: an
    edit, a restore or other Feedback made meanwhile would be lost.
    """
    if post.writing_since is not None and now - as_utc(post.writing_since) < WRITING_TIMEOUT:
        raise VersionBeingWritten(
            "Pumpkit is writing a new version of this post. Try again once it's written."
        )


def start_writing(post: Post, *, now: datetime) -> None:
    """Holds the Text until the Version is recorded, or its attempt fails. Not flushed."""
    check_not_writing(post, now=now)
    post.writing_since = now


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
        raise ConflictError("This post has no text to edit. Start a new post.")
    if len(parts) != len(current):
        raise TextShapeKept(
            f"Editing keeps the text's {len(current)} parts. Give feedback to change its shape."
            if len(current) > 1
            else "Editing keeps the text a single post. Give feedback to make it a thread."
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
    """Lets the Text change again. Flushes."""
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
    post.writing_since = None
    await db.flush()
    return attempt
