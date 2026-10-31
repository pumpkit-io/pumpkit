from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.core.errors import RefusedError
from pumpkit.posts import service
from pumpkit.posts.formats import Format
from pumpkit.posts.llm import LLM
from pumpkit.posts.schemas import PostResponse
from pumpkit.posts.version_writing import (
    char_limit_for,
    charge_generation,
    check_attempt_limit,
    check_generation_left,
    record_failed_attempt,
    version_response,
)
from pumpkit.posts.writing.versions import write_first_version

# Where the User adds Inspiration authors.
PERSONA_PAGE = "/persona"


async def start_post(
    db: AsyncSession, llm: LLM, user: User, brief: str, format: Format, now: datetime
) -> PostResponse:
    """
    Start a Post from the Brief and write its first Version in `format`.

    The Post and its attempt are stored only after the calls, so no transaction stays open
    across them; a failure is stored as a failed attempt before the error is re-raised.
    """
    user_id = user.id
    corpus = await service.corpus_for_user(db, user_id=user_id)
    if not corpus.post_ids:
        raise RefusedError(
            "Add an inspiration author with posts before writing a post.", fix_page=PERSONA_PAGE
        )
    await check_attempt_limit(db, user_id=user_id, now=now)
    await check_generation_left(db, user_id=user_id, now=now)
    char_limit = await char_limit_for(db, user_id=user_id)
    # Ends the read transaction before the calls, which can take minutes.
    await db.commit()

    try:
        written = await write_first_version(llm, corpus, brief, format, char_limit)
    except Exception as error:
        post = await service.create_post(db, user_id=user_id, brief=brief, corpus=corpus, now=now)
        await record_failed_attempt(
            db, post=post, sequence=1, feedback=None, format=format, error=error, now=now
        )
        # Commit before re-raising, or the request session rolls the failed attempt back.
        await db.commit()
        raise

    post = await service.create_post(db, user_id=user_id, brief=brief, corpus=corpus, now=now)
    version = await service.record_version(
        db, post=post, sequence=1, version_number=1, feedback=None, written=written, now=now
    )
    await charge_generation(db, user_id=user_id, version=version, now=now)
    await db.commit()
    return PostResponse(
        id=post.id, brief=post.brief, versions=[version_response(version, char_limit)]
    )
