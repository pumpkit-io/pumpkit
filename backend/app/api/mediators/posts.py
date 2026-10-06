from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.posts as posts_service
from app.core.llm import LLM
from app.db.models import User, VersionAttempt
from app.schemas.posts import PostResponse, TellResponse, VersionResponse
from app.writing.constants import POST_MAX_CHARS
from app.writing.versions import write_first_version


def version_response(attempt: VersionAttempt) -> VersionResponse:
    assert attempt.version_number is not None and attempt.draft is not None
    assert attempt.final is not None and attempt.final_char_count is not None
    assert attempt.slop_tells is not None
    return VersionResponse(
        number=attempt.version_number,
        feedback=attempt.feedback,
        draft=attempt.draft,
        final=attempt.final,
        final_char_count=attempt.final_char_count,
        final_char_limit=POST_MAX_CHARS,
        tells=[TellResponse(**tell) for tell in attempt.slop_tells],
    )


async def start_post(
    db: AsyncSession, llm: LLM, user: User, brief: str, now: datetime
) -> PostResponse:
    """
    Start a Post from the Brief and write its first Version.

    The Post and its attempt are stored only after the calls, so no transaction stays open
    across them; a failure is stored as a failed attempt before the error is re-raised.
    """
    user_id = user.id
    corpus = await posts_service.corpus_for_user(db, user_id=user_id)
    if not corpus.post_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Add an Inspiration author with posts before writing a Post.",
        )
    # Ends the read transaction before the calls, which can take minutes.
    await db.commit()

    try:
        written = await write_first_version(llm, corpus, brief)
    except Exception as error:
        post = await posts_service.create_post(
            db, user_id=user_id, brief=brief, corpus=corpus, now=now
        )
        await posts_service.record_failed_attempt(
            db,
            post=post,
            sequence=1,
            feedback=None,
            error=f"{type(error).__name__}: {error}",
            now=now,
        )
        # Commit before raising, or the request session rolls the failed attempt back.
        await db.commit()
        raise

    post = await posts_service.create_post(db, user_id=user_id, brief=brief, corpus=corpus, now=now)
    version = await posts_service.record_version(
        db, post=post, sequence=1, version_number=1, feedback=None, written=written, now=now
    )
    await db.commit()
    return PostResponse(id=post.id, brief=post.brief, versions=[version_response(version)])
