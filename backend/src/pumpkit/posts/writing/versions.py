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
from pumpkit.posts.writing.prompts.parts import format_text
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


class WrittenThread(_HookedWriting):
    # No minItems or maxItems: not every provider's structured output enforces them, so the
    # Part count is checked after the call.
    parts: list[str]


class DraftedThread(WrittenThread):
    pass


class RevisedThread(WrittenThread):
    pass


class FinalThread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parts: list[str]


# The SDK names the structured-output schema after the class; the post ones are v6's names.
DraftedPost.__name__ = "drafted_post"
FinalPost.__name__ = "refined_post"
RevisedPost.__name__ = "revised_post"
DraftedThread.__name__ = "drafted_thread"
RevisedThread.__name__ = "revised_thread"
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


def humanizer_messages(
    corpus: Corpus, brief: str, format: Format, draft_parts: list[str]
) -> list[dict]:
    """The first Version's humanizer call, as v6 sent it: the Brief, then the scrubbed Draft last."""
    return [*_humanizer_prefix(corpus, brief, format), _user(format_text(format, draft_parts))]


def revision_humanizer_messages(
    corpus: Corpus,
    brief: str,
    previous: EarlierVersion,
    feedback: str,
    format: Format,
    draft_parts: list[str],
) -> list[dict]:
    """
    The first Version's prefix in the new Format, then what keeps the humanizer from rewording
    sentences the Feedback left alone or undoing what it asked for. Earlier asks live on in the
    previous Final, which keeps its own Format.
    """
    return [
        *_humanizer_prefix(corpus, brief, format),
        _user(previous_final_message(previous.format, previous.final_parts)),
        _user(latest_feedback_message(feedback, previous.format, format)),
        _user(revised_draft_message(previous.format, format, draft_parts)),
    ]


def revision_messages(
    corpus: Corpus,
    brief: str,
    earlier: Sequence[EarlierVersion],
    feedback: str,
    format: Format,
) -> list[dict]:
    """
    The draft call's conversation continued, under the new Format's prompt: the Brief, each
    Final in its own Format as the model's answer after the Feedback that asked for it, then
    the new Feedback. A Feedback that switched Format says so. Drafts stay out: the User never
    reacted to them.
    """
    messages = draft_messages(corpus, brief, format)
    previous: Optional[EarlierVersion] = None
    for version in earlier:
        if previous is not None and version.feedback is not None:
            framed = feedback_message(version.feedback, previous.format, version.format)
            messages.append(_user(framed))
        content = format_text(version.format, version.final_parts)
        messages.append({"role": "assistant", "content": content})
        previous = version
    messages.append(_user(feedback_message(feedback, earlier[-1].format, format)))
    return messages


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
    format: Format,
) -> WrittenVersion:
    """
    Write the Version after `earlier` in `format`. Raises whatever the LLM port raises, or an
    `LLMError` for a Thread of the wrong length; nothing is stored here.
    """
    messages = revision_messages(corpus, brief, earlier, feedback, format)
    if format == FORMAT_THREAD:
        revised = await llm.structured(
            model=settings.LLM_REVISING_MODEL,
            messages=messages,
            response_model=RevisedThread,
            max_tokens=MAX_TOKENS,
        )
        draft_parts = [scrub(part) for part in _thread_parts("revision", revised.parsed.parts)]
    else:
        revised = await llm.structured(
            model=settings.LLM_REVISING_MODEL,
            messages=messages,
            response_model=RevisedPost,
            max_tokens=MAX_TOKENS,
        )
        draft_parts = [scrub(revised.parsed.post)]
    messages = revision_humanizer_messages(
        corpus, brief, earlier[-1], feedback, format, draft_parts
    )
    return await _humanize(llm, format, messages, revised, draft_parts, _hook(revised.parsed))


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
