"""A Brief with its Ideas and their Posts as its page reads it (ADR 0025)."""

from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.core.errors import NotFoundError
from pumpkit.core.time import as_utc
from pumpkit.posts import service
from pumpkit.posts.models import Brief, Idea, Post
from pumpkit.posts.schemas import (
    BriefPostResponse,
    BriefResponse,
    IdeaResponse,
    RecentBriefResponse,
    RecentBriefsResponse,
)
from pumpkit.posts.version_writing import (
    char_limit_for,
    generations_left,
    plan_response,
    text_response,
)
from pumpkit.posts.writing_state import NOT_WRITTEN, WRITING, writing_state

# New post lists this many of the User's latest Briefs.
RECENT_BRIEFS = 10
TEXT_START_CHARS = 100
# Read from the database, enough for whitespace collapsed away to leave a full start.
TEXT_START_READ = TEXT_START_CHARS * 4


async def user_brief(db: AsyncSession, *, user: User, brief_id: str) -> Brief:
    brief = await service.get_user_brief(db, user_id=user.id, brief_id=brief_id)
    if brief is None:
        raise NotFoundError("Brief not found.")
    return brief


async def brief_response(
    db: AsyncSession, brief: Brief, posts: dict[str, Post], char_limit: int, *, now: datetime
) -> BriefResponse:
    def post_response(post: Optional[Post]) -> Optional[BriefPostResponse]:
        if post is None:
            return None
        return BriefPostResponse(
            id=post.id,
            writing_state=writing_state(post, now=now),
            text=text_response(post, char_limit),
        )

    return BriefResponse(
        id=brief.id,
        text=brief.text,
        created_at=as_utc(brief.created_at),
        ideas=[
            IdeaResponse(
                id=idea.id,
                posting_order=idea.posting_order,
                whole_brief=idea.whole_brief,
                plan=plan_response(idea.plan),
                post=post_response(posts.get(idea.id)),
            )
            for idea in brief.ideas
        ],
        generations_left=await generations_left(db, user_id=brief.user_id, now=now),
    )


async def read_brief(
    db: AsyncSession, *, user: User, brief_id: str, now: datetime
) -> BriefResponse:
    """The User's Brief with its Ideas and their Posts as they are now."""
    brief = await user_brief(db, user=user, brief_id=brief_id)
    posts = await service.posts_of_ideas(db, idea_ids=[idea.id for idea in brief.ideas])
    char_limit = await char_limit_for(db, user_id=user.id)
    return await brief_response(db, brief, posts, char_limit, now=now)


def offered_ideas(ideas: Sequence[tuple[Idea, Optional[Post]]]) -> list[Idea]:
    """
    The Ideas a Brief's page offers under "Not written" (ADR 0025): only the kind that has a Post,
    the split Ideas when both have; while none has, every split Idea and then the single-post one.
    The web app's `notWrittenIdeas` applies the same rule to the Brief it reads.
    """
    unwritten = [idea for idea, post in ideas if post is None]
    split = [idea for idea in unwritten if not idea.whole_brief]
    written = [idea for idea, post in ideas if post is not None]
    if any(not idea.whole_brief for idea in written):
        return split
    if written:
        return []
    return [*split, *(idea for idea in unwritten if idea.whole_brief)]


def text_start(text: str, *, runs_on: bool = False) -> str:
    """
    The text on one line, cut at the last word that fits with "…" when it runs longer, or when
    `runs_on` says the text given is only its beginning.
    """
    line = " ".join(text.split())
    if len(line) <= TEXT_START_CHARS:
        return f"{line}…" if runs_on else line
    cut = line[:TEXT_START_CHARS]
    space = cut.rfind(" ")
    return f"{(cut[:space] if space > 0 else cut).rstrip()}…"


async def recent_briefs(db: AsyncSession, *, user: User, now: datetime) -> RecentBriefsResponse:
    """The User's latest Briefs, newest first, each with its Posts counted by writing state."""
    # One character past what is read shows whether the text runs on.
    latest = await service.latest_briefs(
        db, user_id=user.id, limit=RECENT_BRIEFS, text_chars=TEXT_START_READ + 1
    )
    ideas = await service.ideas_and_posts_of_briefs(db, brief_ids=[id_ for id_, _, _ in latest])

    def recent(brief_id: str, text: str, created_at: datetime) -> RecentBriefResponse:
        of_brief = ideas.get(brief_id, [])
        posts = [post for _, post in of_brief if post is not None]
        states = [writing_state(post, now=now) for post in posts]
        return RecentBriefResponse(
            id=brief_id,
            text_start=text_start(text[:TEXT_START_READ], runs_on=len(text) > TEXT_START_READ),
            created_at=as_utc(created_at),
            posts_written=states.count(None),
            posts_writing=states.count(WRITING),
            posts_not_written=states.count(NOT_WRITTEN),
            ideas_offered=len(offered_ideas(of_brief)),
            post_ids=[post.id for post in posts],
        )

    return RecentBriefsResponse(data=[recent(*brief) for brief in latest])
