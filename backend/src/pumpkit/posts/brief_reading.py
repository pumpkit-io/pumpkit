"""
Reading Briefs (ADR 0025): one with its Ideas and their Posts as its page reads it, and the
User's latest as New post lists them.
"""

import unicodedata
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
from pumpkit.posts.writing_state import NOT_WRITTEN, WRITING, WritingState, writing_state

# New post lists this many of the User's latest Briefs.
RECENT_BRIEFS = 10
TEXT_START_CHARS = 100
# Briefs run to 200,000 characters, so only this much is read. Four times the start still fills it
# unless whitespace takes three quarters of what is read; then the start is shorter, at a whole word.
TEXT_START_READ = TEXT_START_CHARS * 4
_MARKS = {"Mn", "Mc", "Me"}
_ZWJ = "\u200d"
_EMOJI_MODIFIERS = ("\U0001f3fb", "\U0001f3ff")
_TAGS = ("\U000e0020", "\U000e007f")
_REGIONAL_INDICATORS = ("\U0001f1e6", "\U0001f1ff")


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
    The web app's `notWrittenIdeas` applies the same rule to the Brief it reads; both run the cases in
    `tests/posts/offered_ideas_cases.json`.
    """
    unwritten = [idea for idea, post in ideas if post is None]
    split = [idea for idea in unwritten if not idea.whole_brief]
    written = [idea for idea, post in ideas if post is not None]
    if any(not idea.whole_brief for idea in written):
        return split
    if written:
        return []
    return [*split, *(idea for idea in unwritten if idea.whole_brief)]


def _continues(line: str, at: int) -> bool:
    """Whether the character at `at` joins the one before it into what a reader sees as one."""
    char = line[at]
    if unicodedata.category(char) in _MARKS or line[at - 1] == _ZWJ or char == _ZWJ:
        return True
    if _EMOJI_MODIFIERS[0] <= char <= _EMOJI_MODIFIERS[1] or _TAGS[0] <= char <= _TAGS[1]:
        return True
    if not _is_regional_indicator(char):
        return False
    # Flags are pairs of regional indicators, so an odd run before `at` is half a flag.
    run = 0
    while at - run - 1 >= 0 and _is_regional_indicator(line[at - run - 1]):
        run += 1
    return run % 2 == 1


def _is_regional_indicator(char: str) -> bool:
    return _REGIONAL_INDICATORS[0] <= char <= _REGIONAL_INDICATORS[1]


def _cut(line: str, at: int) -> str:
    """`line` up to `at`, at the last space when one ends a word before it, else between characters."""
    if line[at] == " ":
        return line[:at]
    space = line.rfind(" ", 0, at)
    if space > 0:
        return line[:space]
    while at > 1 and _continues(line, at):
        at -= 1
    return line[:at]


def text_start(read: str) -> str:
    """
    The text on one line, cut at the last word that fits with "…" when it runs longer. `read` is the
    text's first `TEXT_START_READ` characters and one more when there are more, as Briefs are read.
    """
    runs_on = len(read) > TEXT_START_READ
    window = read[:TEXT_START_READ]
    if runs_on and not read[TEXT_START_READ].isspace():
        # The read stopped inside a word, which is left out unless it is all that was read.
        last_space = max((i for i, c in enumerate(window) if c.isspace()), default=0)
        window = window[:last_space] if last_space else window
    line = " ".join(window.split())
    if len(line) <= TEXT_START_CHARS:
        return f"{line}…" if runs_on else line
    return f"{_cut(line, TEXT_START_CHARS)}…"


async def recent_briefs(db: AsyncSession, *, user: User, now: datetime) -> RecentBriefsResponse:
    """The User's latest Briefs, newest first, each with its Posts counted by writing state."""
    # One character past what is read shows whether the text runs on.
    latest = await service.latest_briefs(
        db, user_id=user.id, limit=RECENT_BRIEFS, text_chars=TEXT_START_READ + 1
    )
    ideas = await service.ideas_and_posts_of_briefs(db, brief_ids=[id_ for id_, _ in latest])

    def listed_state(post: Post) -> Optional[WritingState]:
        # "Writing…" means a Post the User hasn't seen, so one rewritten from Feedback is written.
        state = writing_state(post, now=now)
        return None if state == WRITING and post.text_version_number is not None else state

    def recent(brief_id: str, text: str) -> RecentBriefResponse:
        of_brief = ideas.get(brief_id, [])
        posts = [post for _, post in of_brief if post is not None]
        states = [listed_state(post) for post in posts]
        return RecentBriefResponse(
            id=brief_id,
            text_start=text_start(text),
            posts_written=states.count(None),
            posts_writing=states.count(WRITING),
            posts_not_written=states.count(NOT_WRITTEN),
            ideas_offered=len(offered_ideas(of_brief)),
            post_ids=[post.id for post in posts],
        )

    return RecentBriefsResponse(data=[recent(*brief) for brief in latest])
