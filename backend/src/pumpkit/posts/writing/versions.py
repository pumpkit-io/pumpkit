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
from pumpkit.posts.formats import FORMAT_POST, FORMAT_THREAD, Format
from pumpkit.posts.llm import LLM, LLMError
from pumpkit.posts.llm_schemas import StructuredResult
from pumpkit.posts.writing.constants import (
    CACHE_TTL,
    MAX_TOKENS,
    THREAD_MAX_PARTS,
    THREAD_MIN_PARTS,
)
from pumpkit.posts.writing.corpus import Corpus
from pumpkit.posts.writing.prompts.brief import brief_message
from pumpkit.posts.writing.prompts.corpus import context_message
from pumpkit.posts.writing.prompts.draft_post import DRAFT_POST_PROMPT
from pumpkit.posts.writing.prompts.draft_thread import DRAFT_THREAD_PROMPT
from pumpkit.posts.writing.prompts.feedback import feedback_message
from pumpkit.posts.writing.prompts.hook import HOOK_NAMES
from pumpkit.posts.writing.prompts.humanizer import HUMANIZER_PROMPT
from pumpkit.posts.writing.prompts.humanizer_thread import HUMANIZER_THREAD_PROMPT
from pumpkit.posts.writing.prompts.parts import numbered_parts
from pumpkit.posts.writing.prompts.revision_humanizer import (
    latest_feedback_message,
    previous_final_message,
    revised_draft_message,
)
from pumpkit.posts.writing.scrub import scrub


class _HookedWriting(BaseModel):
    # hook_reasoning comes first so the model settles the opening before it writes the text.
    model_config = ConfigDict(extra="forbid")

    hook_reasoning: str
    hook_name: Optional[str]


class WrittenPost(_HookedWriting):
    post: str


class DraftedPost(WrittenPost):
    pass


class FinalPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post: str


class RevisedPost(WrittenPost):
    pass


class DraftedThread(_HookedWriting):
    # No minItems or maxItems: not every provider's structured output enforces them, so the
    # Part count is checked after the call.
    parts: list[str]


class FinalThread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parts: list[str]


# The SDK names the structured-output schema after the class; the post ones are v6's names.
DraftedPost.__name__ = "drafted_post"
FinalPost.__name__ = "refined_post"
RevisedPost.__name__ = "revised_post"
DraftedThread.__name__ = "drafted_thread"
FinalThread.__name__ = "refined_thread"

_DRAFT_PROMPTS: dict[Format, str] = {
    FORMAT_POST: DRAFT_POST_PROMPT,
    FORMAT_THREAD: DRAFT_THREAD_PROMPT,
}
_HUMANIZER_PROMPTS: dict[Format, str] = {
    FORMAT_POST: HUMANIZER_PROMPT,
    FORMAT_THREAD: HUMANIZER_THREAD_PROMPT,
}


@dataclass(frozen=True)
class EarlierVersion:
    # None for the first Version, which comes from the Brief.
    feedback: Optional[str]
    format: Format
    final_parts: list[str]


@dataclass(frozen=True)
class Hook:
    reasoning: str
    # None when the post opens with no library Hook, or names one the library doesn't have.
    name: Optional[str]


@dataclass(frozen=True)
class WrittenVersion:
    format: Format
    draft_parts: list[str]
    final_parts: list[str]
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


def draft_messages(corpus: Corpus, brief: str, format: Format) -> list[dict]:
    return [_system(_DRAFT_PROMPTS[format]), _user(context_message(corpus)), _user(brief)]


def _humanizer_prefix(corpus: Corpus, brief: str, format: Format) -> list[dict]:
    return [
        _system(_HUMANIZER_PROMPTS[format]),
        _user(context_message(corpus)),
        _user(brief_message(brief, format)),
    ]


def _draft_text(format: Format, draft_parts: list[str]) -> str:
    if format == FORMAT_THREAD:
        return numbered_parts(draft_parts)
    [text] = draft_parts
    return text


def humanizer_messages(
    corpus: Corpus, brief: str, format: Format, draft_parts: list[str]
) -> list[dict]:
    """The first Version's humanizer call, as v6 sent it: the Brief, then the scrubbed Draft last."""
    return [*_humanizer_prefix(corpus, brief, format), _user(_draft_text(format, draft_parts))]


def revision_humanizer_messages(
    corpus: Corpus, brief: str, previous_final: str, feedback: str, draft: str
) -> list[dict]:
    """
    The first Version's prefix, then what keeps the humanizer from rewording sentences the
    Feedback left alone or undoing what it asked for. Earlier asks live on in the previous Final.
    """
    return [
        *_humanizer_prefix(corpus, brief, FORMAT_POST),
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
    messages = draft_messages(corpus, brief, FORMAT_POST)
    for version in earlier:
        if version.feedback is not None:
            messages.append(_user(feedback_message(version.feedback)))
        messages.append({"role": "assistant", "content": _final_text(version)})
    messages.append(_user(feedback_message(feedback)))
    return messages


def _final_text(version: EarlierVersion) -> str:
    """A single X post's Final as the model wrote it; only that Format is written so far."""
    assert version.format == FORMAT_POST
    [text] = version.final_parts
    return text


def _usage(result: StructuredResult) -> Optional[dict]:
    return None if result.usage is None else result.usage.raw


def _thread_parts(call: str, parts: list[str]) -> list[str]:
    """A Thread reply's Parts, or an `LLMError` that fails the attempt: a Thread is never cut."""
    if not THREAD_MIN_PARTS <= len(parts) <= THREAD_MAX_PARTS:
        raise LLMError(
            f"The {call} call wrote {len(parts)} Parts; "
            f"a Thread has {THREAD_MIN_PARTS} to {THREAD_MAX_PARTS}"
        )
    if any(not part.strip() for part in parts):
        raise LLMError(f"The {call} call wrote a blank Part")
    return parts


async def write_first_version(
    llm: LLM, corpus: Corpus, brief: str, format: Format
) -> WrittenVersion:
    """Raises whatever the LLM port raises, or an `LLMError` for a Thread of the wrong length."""
    messages = draft_messages(corpus, brief, format)
    if format == FORMAT_THREAD:
        drafted = await llm.structured(
            model=settings.LLM_DRAFTING_MODEL,
            messages=messages,
            response_model=DraftedThread,
            max_tokens=MAX_TOKENS,
        )
        draft_parts = [scrub(part) for part in _thread_parts("draft", drafted.parsed.parts)]
    else:
        drafted = await llm.structured(
            model=settings.LLM_DRAFTING_MODEL,
            messages=messages,
            response_model=DraftedPost,
            max_tokens=MAX_TOKENS,
        )
        draft_parts = [scrub(drafted.parsed.post)]
    messages = humanizer_messages(corpus, brief, format, draft_parts)
    return await _humanize(llm, format, messages, drafted, draft_parts, _hook(drafted.parsed))


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
    previous_final = _final_text(earlier[-1])
    messages = revision_humanizer_messages(corpus, brief, previous_final, feedback, draft)
    return await _humanize(llm, FORMAT_POST, messages, revised, [draft], _hook(revised.parsed))


def _hook(written: _HookedWriting) -> Hook:
    """An unknown name is dropped, not refused: the post is worth more than its Hook's label."""
    name = written.hook_name
    if name is not None and name not in HOOK_NAMES:
        logger.warning("The writing call named an unknown hook %r, stored as none", name)
        name = None
    return Hook(reasoning=written.hook_reasoning, name=name)


async def _humanize(
    llm: LLM,
    format: Format,
    messages: list[dict],
    written: StructuredResult,
    draft_parts: list[str],
    hook: Hook,
) -> WrittenVersion:
    if format == FORMAT_THREAD:
        refined = await llm.structured(
            model=settings.LLM_HUMANIZING_MODEL,
            messages=messages,
            response_model=FinalThread,
            max_tokens=MAX_TOKENS,
        )
        final_parts = _thread_parts("humanizer", refined.parsed.parts)
    else:
        refined = await llm.structured(
            model=settings.LLM_HUMANIZING_MODEL,
            messages=messages,
            response_model=FinalPost,
            max_tokens=MAX_TOKENS,
        )
        final_parts = [refined.parsed.post]
    return WrittenVersion(
        format=format,
        draft_parts=draft_parts,
        final_parts=final_parts,
        writing_model=written.model,
        humanizing_model=refined.model,
        writing_usage=_usage(written),
        humanizing_usage=_usage(refined),
        hook=hook,
    )
