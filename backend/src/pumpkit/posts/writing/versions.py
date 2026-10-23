"""
Writing a Version, the pumpkit-v6 way: the writing call (the draft call for the first Version,
the revision call after Feedback), which chooses and writes the Hook too, the scrub, then the
humanizer call.

The scrubbed writing-call text is the Draft and the humanizer's text is the Final. Every call
gets the system prompt first and the corpus second, as in v6, so the per-call parts come after a
prefix that stays the same across a Post's Versions.
"""

from dataclasses import dataclass
from typing import Optional, Sequence

from pydantic import BaseModel, ConfigDict

from pumpkit.core.config import settings
from pumpkit.core.logging import logger
from pumpkit.posts.llm import LLM
from pumpkit.posts.llm_schemas import StructuredResult
from pumpkit.posts.writing.constants import CACHE_TTL, MAX_TOKENS
from pumpkit.posts.writing.corpus import Corpus
from pumpkit.posts.writing.prompts.brief import brief_message
from pumpkit.posts.writing.prompts.corpus import context_message
from pumpkit.posts.writing.prompts.draft_post import DRAFT_POST_PROMPT
from pumpkit.posts.writing.prompts.feedback import feedback_message
from pumpkit.posts.writing.prompts.hook import HOOK_NAMES
from pumpkit.posts.writing.prompts.humanizer import HUMANIZER_PROMPT
from pumpkit.posts.writing.prompts.revision_humanizer import (
    latest_feedback_message,
    previous_final_message,
    revised_draft_message,
)
from pumpkit.posts.writing.scrub import scrub


class WrittenPost(BaseModel):
    # hook_reasoning comes first so the model settles the opening before it writes the post.
    model_config = ConfigDict(extra="forbid")

    hook_reasoning: str
    hook_name: Optional[str]
    post: str


class DraftedPost(WrittenPost):
    pass


class FinalPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post: str


class RevisedPost(WrittenPost):
    pass


# The SDK names the structured-output schema after the class; these are v6's schema names.
DraftedPost.__name__ = "drafted_post"
FinalPost.__name__ = "refined_post"
RevisedPost.__name__ = "revised_post"


@dataclass(frozen=True)
class EarlierVersion:
    # None for the first Version, which comes from the Brief.
    feedback: Optional[str]
    final: str


@dataclass(frozen=True)
class Hook:
    reasoning: str
    # None when the post opens with no library Hook, or names one the library doesn't have.
    name: Optional[str]


@dataclass(frozen=True)
class WrittenVersion:
    draft: str
    final: str
    writing_model: str
    humanizing_model: str
    writing_usage: Optional[dict]
    humanizing_usage: Optional[dict]
    hook: Hook


def _system(prompt: str) -> dict:
    # The only cache breakpoint, as in v6: the system prompt is what every call of every Post shares.
    cache_control = {"type": "ephemeral", "ttl": CACHE_TTL}
    return {
        "role": "system",
        "content": [{"type": "text", "text": prompt, "cache_control": cache_control}],
    }


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


def draft_messages(corpus: Corpus, brief: str) -> list[dict]:
    return [_system(DRAFT_POST_PROMPT), _user(context_message(corpus)), _user(brief)]


def _humanizer_prefix(corpus: Corpus, brief: str) -> list[dict]:
    return [_system(HUMANIZER_PROMPT), _user(context_message(corpus)), _user(brief_message(brief))]


def humanizer_messages(corpus: Corpus, brief: str, draft: str) -> list[dict]:
    """The first Version's humanizer call, as v6 sent it: the Brief, then the scrubbed Draft last."""
    return [*_humanizer_prefix(corpus, brief), _user(draft)]


def revision_humanizer_messages(
    corpus: Corpus, brief: str, previous_final: str, feedback: str, draft: str
) -> list[dict]:
    """
    The first Version's prefix, then what keeps the humanizer from rewording sentences the
    Feedback left alone or undoing what it asked for. Earlier asks live on in the previous Final.
    """
    return [
        *_humanizer_prefix(corpus, brief),
        _user(previous_final_message(previous_final)),
        _user(latest_feedback_message(feedback)),
        _user(revised_draft_message(draft)),
    ]


def revision_messages(
    corpus: Corpus,
    brief: str,
    earlier: Sequence[EarlierVersion],
    feedback: str,
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
        model=settings.LLM_DRAFTING_MODEL,
        messages=draft_messages(corpus, brief),
        response_model=DraftedPost,
        max_tokens=MAX_TOKENS,
    )
    draft = scrub(drafted.parsed.post)
    messages = humanizer_messages(corpus, brief, draft)
    return await _humanize(llm, messages, drafted, draft, _hook(drafted.parsed))


async def write_next_version(
    llm: LLM,
    corpus: Corpus,
    brief: str,
    earlier: Sequence[EarlierVersion],
    feedback: str,
) -> WrittenVersion:
    """Raises whatever the LLM port raises; nothing is stored here."""
    revised = await llm.structured(
        model=settings.LLM_REVISING_MODEL,
        messages=revision_messages(corpus, brief, earlier, feedback),
        response_model=RevisedPost,
        max_tokens=MAX_TOKENS,
    )
    draft = scrub(revised.parsed.post)
    messages = revision_humanizer_messages(corpus, brief, earlier[-1].final, feedback, draft)
    return await _humanize(llm, messages, revised, draft, _hook(revised.parsed))


def _hook(written: WrittenPost) -> Hook:
    """An unknown name is dropped, not refused: the post is worth more than its Hook's label."""
    name = written.hook_name
    if name is not None and name not in HOOK_NAMES:
        logger.warning("The writing call named an unknown hook %r, stored as none", name)
        name = None
    return Hook(reasoning=written.hook_reasoning, name=name)


async def _humanize(
    llm: LLM,
    messages: list[dict],
    written: StructuredResult,
    draft: str,
    hook: Hook,
) -> WrittenVersion:
    refined = await llm.structured(
        model=settings.LLM_HUMANIZING_MODEL,
        messages=messages,
        response_model=FinalPost,
        max_tokens=MAX_TOKENS,
    )
    return WrittenVersion(
        draft=draft,
        final=refined.parsed.post,
        writing_model=written.model,
        humanizing_model=refined.model,
        writing_usage=_usage(written),
        humanizing_usage=_usage(refined),
        hook=hook,
    )
