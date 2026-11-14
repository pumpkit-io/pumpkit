"""A Brief with its Ideas and their Posts as its page reads it (ADR 0025)."""

from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.core.errors import NotFoundError
from pumpkit.core.time import as_utc
from pumpkit.posts import service
from pumpkit.posts.models import Brief, Post
from pumpkit.posts.schemas import BriefPostResponse, BriefResponse, IdeaResponse
from pumpkit.posts.version_writing import (
    char_limit_for,
    generations_left,
    plan_response,
    text_response,
)
from pumpkit.posts.writing_state import writing_state


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
