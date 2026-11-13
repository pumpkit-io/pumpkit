import logging
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO, Literal

from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.auth.service.users as users_service
from pumpkit.auth.models import User
from pumpkit.core.errors import NotFoundError, RefusedError
from pumpkit.core.llm import LLM
from pumpkit.core.storage import FileStorage
from pumpkit.positioning import service as positioning_service
from pumpkit.posts import media as media_service
from pumpkit.posts import service
from pumpkit.posts.formats import FORMAT_THREAD, Format
from pumpkit.posts.media_files import PREVIEW_CONTENT_TYPE
from pumpkit.posts.models import Idea, Post
from pumpkit.posts.schemas import PostResponse
from pumpkit.posts.version_writing import (
    char_limit_for,
    charge_generation,
    check_attempt_limit,
    check_generation_left,
    plan_response,
    record_failed_attempt,
    version_response,
)
from pumpkit.posts.writing.planning import plan_brief
from pumpkit.posts.writing.post_writing import write_post
from pumpkit.posts.writing.prompts.post import PostInputs
from pumpkit.posts.writing.versions import write_first_version

logger = logging.getLogger(__name__)

# Where the User saves their Positioning and adds Inspiration authors.
PERSONA_PAGE = "/persona"


async def start_post(
    db: AsyncSession, llm: LLM, user: User, brief: str, format: Format, now: datetime
) -> PostResponse:
    """
    Plan the Brief with the User's Positioning, then start a Post from its single-post Idea
    and write its first Version: a single post from its Plan, a Thread from the corpus.

    The Brief, its Ideas, the Post and its attempt are stored only after the calls, so no
    transaction stays open across them. A failed plan stores nothing; a failed write is stored
    as a failed attempt before the error is re-raised.
    """
    user_id = user.id
    positioning = await positioning_service.get_positioning(db, user_id=user_id)
    if positioning is None:
        raise RefusedError("Set up your persona before writing a post.", fix_page=PERSONA_PAGE)
    corpus = await service.corpus_for_user(db, user_id=user_id)
    # Only a Thread is still written from the Inspiration authors' posts.
    if format == FORMAT_THREAD and not corpus.post_ids:
        raise RefusedError(
            "Add an inspiration author with posts before writing a post.", fix_page=PERSONA_PAGE
        )
    await check_attempt_limit(db, user_id=user_id, now=now)
    await check_generation_left(db, user_id=user_id, now=now)
    char_limit = await char_limit_for(db, user_id=user_id)
    # Ends the read transaction before the calls, which can take minutes.
    await db.commit()

    planned = await plan_brief(
        llm,
        user_id=user_id,
        brief=brief,
        positioning=positioning.text,
        format=format,
        char_limit=char_limit,
    )

    async def store_post() -> tuple[Idea, Post]:
        idea = await service.store_planned_brief(
            db, user_id=user_id, text=brief, planned=planned, now=now
        )
        post = await service.create_post(db, user_id=user_id, idea=idea, corpus=corpus, now=now)
        return idea, post

    try:
        if planned.single.format == FORMAT_THREAD:
            written = await write_first_version(llm, corpus, brief, format, char_limit)
        else:
            inputs = PostInputs(
                brief=brief,
                positioning=positioning.text,
                plan=planned.single,
                char_limit=char_limit,
            )
            written = await write_post(llm, inputs, user_id=user_id)
    except Exception as error:
        _, post = await store_post()
        await record_failed_attempt(
            db, post=post, sequence=1, feedback=None, format=format, error=error, now=now
        )
        # Commit before re-raising, or the request session rolls the failed attempt back.
        await db.commit()
        raise

    # Before the insert: its key share on the User deadlocks two requests upgrading it to charge.
    await users_service.lock_user_id(db, user_id=user_id)
    idea, post = await store_post()
    if written.first_reply is not None:
        logger.info("Post %s: the first reply the writing added is dropped", post.id)
    version = await service.record_version(
        db, post=post, sequence=1, version_number=1, feedback=None, written=written, now=now
    )
    await charge_generation(db, user_id=user_id, version=version, now=now)
    await db.commit()
    return PostResponse(
        id=post.id,
        brief=post.brief,
        plan=plan_response(idea.plan),
        versions=[version_response(version, char_limit)],
    )


@dataclass(frozen=True)
class StoredFile:
    """An open file the caller streams and closes."""

    file: BinaryIO
    content_type: str


async def open_media_file(
    db: AsyncSession,
    storage: FileStorage,
    user: User,
    media_id: str,
    which: Literal["preview", "file"],
) -> StoredFile:
    """The preview or the file of the User's Media, open for reading."""
    media = await media_service.get_user_media(db, user_id=user.id, media_id=media_id)
    if media is None:
        raise NotFoundError("Media not found.")
    if which == "preview":
        key, content_type = media.preview_key, PREVIEW_CONTENT_TYPE
    else:
        key, content_type = media.file_key, media.content_type
    if key is None:
        raise NotFoundError("This media's file isn't kept any more.")
    # Ends the read transaction, so no connection stays held while the file streams.
    await db.commit()
    return StoredFile(file=await storage.open(key), content_type=content_type)
