"""
Writing a Version, the pumpkit-v6 way: the writing call (the draft call for the first
Version, the revision call after Feedback), the scrub, then the humanizer call.

The scrubbed writing-call text is the Draft and the humanizer's text is the Final. Every
call gets the system prompt first and the corpus second, as in v6, so the per-call parts
come after a prefix that stays the same across a Post's Versions.
"""

from dataclasses import dataclass
from typing import Optional, Sequence

from pydantic import BaseModel, ConfigDict

from app.core.llm import LLM
from app.schemas.openrouter import StructuredResult
from app.writing.constants import HUMANIZING_MODEL, MAX_TOKENS, REVISING_MODEL, WRITING_MODEL
from app.writing.corpus import Corpus
from app.writing.prompts.brief import brief_message
from app.writing.prompts.corpus import context_message
from app.writing.prompts.draft_post import DRAFT_POST_PROMPT
from app.writing.prompts.feedback import feedback_message
from app.writing.prompts.humanizer import HUMANIZER_PROMPT
from app.writing.scrub import scrub


class DraftedPost(BaseModel):
    # A single field leaves the model no room for commentary around the post.
    model_config = ConfigDict(extra="forbid")

    post: str


class RefinedPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post: str


class RevisedPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post: str


# The SDK names the structured-output schema after the class; these are v6's schema names.
DraftedPost.__name__ = "drafted_post"
RefinedPost.__name__ = "refined_post"
RevisedPost.__name__ = "revised_post"


@dataclass(frozen=True)
class EarlierVersion:
    # None for the first Version, which comes from the Brief.
    feedback: Optional[str]
    final: str


@dataclass(frozen=True)
class WrittenVersion:
    draft: str
    final: str
    writing_model: str
    humanizing_model: str
    writing_usage: Optional[dict]
    humanizing_usage: Optional[dict]


def _system(prompt: str) -> dict:
    # A list of one text block, as v6 sends it, so a cache breakpoint can be added to it.
    return {"role": "system", "content": [{"type": "text", "text": prompt}]}


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


def draft_messages(corpus: Corpus, brief: str) -> list[dict]:
    return [_system(DRAFT_POST_PROMPT), _user(context_message(corpus)), _user(brief)]


def humanizer_messages(corpus: Corpus, brief: str, draft: str) -> list[dict]:
    """The humanizer gets the original Brief, never Feedback, and the scrubbed Draft last."""
    return [
        _system(HUMANIZER_PROMPT),
        _user(context_message(corpus)),
        _user(brief_message(brief)),
        _user(draft),
    ]


def revision_messages(
    corpus: Corpus, brief: str, earlier: Sequence[EarlierVersion], feedback: str
) -> list[dict]:
    """
    The draft call's conversation continued: the Brief, each Final as the model's answer after
    the Feedback that asked for it, then the new Feedback. Drafts stay out: the User never
    reacted to them.
    """
    messages = [_system(DRAFT_POST_PROMPT), _user(context_message(corpus)), _user(brief)]
    for version in earlier:
        if version.feedback is not None:
            messages.append(_user(feedback_message(version.feedback)))
        messages.append({"role": "assistant", "content": version.final})
    messages.append(_user(feedback_message(feedback)))
    return messages


def _usage(result: StructuredResult) -> Optional[dict]:
    return None if result.usage is None else result.usage.raw


async def write_first_version(llm: LLM, corpus: Corpus, brief: str) -> WrittenVersion:
    """Raises whatever the LLM port raises; nothing is stored here."""
    drafted = await llm.structured(
        model=WRITING_MODEL,
        messages=draft_messages(corpus, brief),
        response_model=DraftedPost,
        max_tokens=MAX_TOKENS,
    )
    draft = scrub(drafted.parsed.post)
    return await _humanize(llm, corpus, brief, draft, drafted)


async def write_next_version(
    llm: LLM, corpus: Corpus, brief: str, earlier: Sequence[EarlierVersion], feedback: str
) -> WrittenVersion:
    """Raises whatever the LLM port raises; nothing is stored here."""
    revised = await llm.structured(
        model=REVISING_MODEL,
        messages=revision_messages(corpus, brief, earlier, feedback),
        response_model=RevisedPost,
        max_tokens=MAX_TOKENS,
    )
    draft = scrub(revised.parsed.post)
    return await _humanize(llm, corpus, brief, draft, revised)


async def _humanize(
    llm: LLM, corpus: Corpus, brief: str, draft: str, written: StructuredResult
) -> WrittenVersion:
    refined = await llm.structured(
        model=HUMANIZING_MODEL,
        messages=humanizer_messages(corpus, brief, draft),
        response_model=RefinedPost,
        max_tokens=MAX_TOKENS,
    )
    return WrittenVersion(
        draft=draft,
        final=refined.parsed.post,
        writing_model=written.model,
        humanizing_model=refined.model,
        writing_usage=_usage(written),
        humanizing_usage=_usage(refined),
    )
