"""
Writing a Version from Feedback, the pumpkit-v6 way, as a Thread's Feedback still is: the revision
call, which continues the sketch call's conversation and chooses and writes the Hook too, the
scrub, then the humanizer call.

The scrubbed writing-call text is the Sketch and the humanizer's text is the Version's text. Every call
gets the system prompt first and the corpus second, as in v6, so the per-call parts come after a
prefix that stays the same across a Post's Versions.
"""

from dataclasses import dataclass, replace
from typing import Callable, Optional, Sequence

from pydantic import BaseModel, ConfigDict

from pumpkit.core.config import settings
from pumpkit.core.llm import LLM, LLMError
from pumpkit.core.llm_schemas import StructuredResult
from pumpkit.core.logging import logger
from pumpkit.posts.formats import FORMAT_POST, FORMAT_THREAD, Format
from pumpkit.posts.writing.constants import (
    CACHE_TTL,
    MAX_TOKENS,
    THREAD_MAX_PARTS,
    THREAD_MIN_PARTS,
)
from pumpkit.posts.writing.corpus import Corpus
from pumpkit.posts.writing.prompts.brief import brief_message
from pumpkit.posts.writing.prompts.corpus import context_message
from pumpkit.posts.writing.prompts.feedback import (
    changed_message,
    feedback_message,
    went_back_message,
)
from pumpkit.posts.writing.prompts.hook import HOOK_NAMES
from pumpkit.posts.writing.prompts.humanizer import HUMANIZER_PROMPT
from pumpkit.posts.writing.prompts.humanizer_thread import humanizer_thread_prompt
from pumpkit.posts.writing.prompts.parts import format_text
from pumpkit.posts.writing.prompts.revision_humanizer import (
    earlier_feedback_message,
    hand_written_message,
    latest_feedback_message,
    previous_final_message,
    revised_sketch_message,
)
from pumpkit.posts.writing.prompts.sketch_post import sketch_post_prompt
from pumpkit.posts.writing.prompts.sketch_thread import sketch_thread_prompt
from pumpkit.posts.writing.scrub import scrub
from pumpkit.posts.writing.starting_text import StartingText, hand_written_sentences
from pumpkit.x_connection.x_length import x_weighted_length


class _HookedWriting(BaseModel):
    # hook_reasoning comes first so the model settles the opening before it writes the text.
    model_config = ConfigDict(extra="forbid")

    hook_reasoning: str
    hook_name: Optional[str]


class WrittenPost(_HookedWriting):
    post: str


class FinalPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post: str


class RevisedPost(WrittenPost):
    pass


class WrittenThread(_HookedWriting):
    # No minItems or maxItems: not every provider's structured output enforces them, so the
    # Part count is checked after the call.
    parts: list[str]


class RevisedThread(WrittenThread):
    pass


class FinalThread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parts: list[str]


# The SDK names the structured-output schema after the class. The model reads these names, so
# they stay the ones the prompts were tuned with, v6's.
FinalPost.__name__ = "refined_post"
RevisedPost.__name__ = "revised_post"
RevisedThread.__name__ = "revised_thread"
FinalThread.__name__ = "refined_thread"

# Each takes the account's character limit. The single-post humanizer states none: it stays v6's.
_SKETCH_PROMPTS: dict[Format, Callable[[int], str]] = {
    FORMAT_POST: sketch_post_prompt,
    FORMAT_THREAD: sketch_thread_prompt,
}
_HUMANIZER_PROMPTS: dict[Format, Callable[[int], str]] = {
    FORMAT_POST: lambda _char_limit: HUMANIZER_PROMPT,
    FORMAT_THREAD: humanizer_thread_prompt,
}
_REVISED: dict[Format, type[_HookedWriting]] = {
    FORMAT_POST: RevisedPost,
    FORMAT_THREAD: RevisedThread,
}
_FINAL: dict[Format, type[BaseModel]] = {
    FORMAT_POST: FinalPost,
    FORMAT_THREAD: FinalThread,
}


@dataclass(frozen=True)
class EarlierVersion:
    number: int
    # None for the first Version, which comes from the Brief.
    feedback: Optional[str]
    format: Format
    parts: list[str]
    first_reply: bool
    starting_text: Optional[StartingText] = None


@dataclass(frozen=True)
class Hook:
    reasoning: str
    # None when the post opens with no library Hook, or names one the library doesn't have.
    name: Optional[str]


@dataclass(frozen=True)
class WrittenVersion:
    format: Format
    sketch_parts: list[str]
    parts: list[str]
    sketch_model: str
    humanizing_model: str
    sketch_usage: Optional[dict]
    humanizing_usage: Optional[dict]
    # The library Hook of a Version written with a corpus; the revise call's reasoning, with no
    # name, on one revised from a Plan; None on a first Version written from a Plan.
    hook: Optional[Hook] = None
    # What the merge chose on a first Version written from a Plan; the revise call names a CTA only.
    hook_levers: Optional[list[str]] = None
    hook_types: Optional[list[str]] = None
    cta_type: Optional[str] = None
    # Every sketch call and the merge's reviews and reasoning. Only kept, never shown.
    sketches: Optional[list[dict]] = None
    merge: Optional[dict] = None
    # Whether the last of `parts` is a single post's first reply (ADR 0027).
    first_reply: bool = False


def system_message(prompt: str) -> dict:
    # The only cache breakpoint, as in v6: the system prompt is what every call of every Post shares.
    cache_control = {"type": "ephemeral", "ttl": CACHE_TTL}
    return {
        "role": "system",
        "content": [{"type": "text", "text": prompt, "cache_control": cache_control}],
    }


def user_message(content: str) -> dict:
    return {"role": "user", "content": content}


def sketch_messages(corpus: Corpus, brief: str, format: Format, char_limit: int) -> list[dict]:
    return [
        system_message(_SKETCH_PROMPTS[format](char_limit)),
        user_message(context_message(corpus)),
        user_message(brief),
    ]


def _humanizer_prefix(corpus: Corpus, brief: str, format: Format, char_limit: int) -> list[dict]:
    return [
        system_message(_HUMANIZER_PROMPTS[format](char_limit)),
        user_message(context_message(corpus)),
        user_message(brief_message(brief, format)),
    ]


def revision_humanizer_messages(
    corpus: Corpus,
    brief: str,
    earlier: Sequence[EarlierVersion],
    starting: Optional[StartingText],
    feedback: str,
    format: Format,
    char_limit: int,
    sketch_parts: list[str],
) -> list[dict]:
    """
    The first Version's prefix in the new Format, then what keeps the humanizer from rewording
    sentences the Feedback left alone, undoing what any Feedback asked for, or rewording what the
    User wrote by hand. The text the Feedback was given on, the Starting text or else the latest
    Version's, keeps its own Format.
    """
    previous = earlier[-1] if starting is None else starting
    messages = _humanizer_prefix(corpus, brief, format, char_limit)
    earlier_feedback = [v.feedback for v in earlier if v.feedback is not None]
    if earlier_feedback:
        messages.append(user_message(earlier_feedback_message(earlier_feedback)))
    messages.append(
        user_message(
            previous_final_message(
                previous.format, previous.parts, first_reply=previous.first_reply
            )
        )
    )
    messages.append(user_message(latest_feedback_message(feedback, previous.format, format)))
    written_by_hand = hand_written(earlier, starting)
    if written_by_hand:
        messages.append(user_message(hand_written_message(written_by_hand, format)))
    messages.append(user_message(revised_sketch_message(previous.format, format, sketch_parts)))
    return messages


def hand_written(earlier: Sequence[EarlierVersion], starting: Optional[StartingText]) -> list[str]:
    """The sentences the User wrote into `starting` by hand; none when there is no Starting text."""
    if starting is None:
        return []
    began_from = next(v for v in earlier if v.number == starting.version_number)
    return hand_written_sentences(starting, began_from.parts)


def _framed_feedback(
    feedback: str,
    earlier: Sequence[EarlierVersion],
    starting: Optional[StartingText],
    format: Format,
) -> str:
    """
    Feedback given after the last of `earlier`, saying first what the User did to the Text: the
    same text as an earlier Version reads as going back to it, whatever the edits that led there.
    """
    after = earlier[-1]
    if starting is None:
        return feedback_message(feedback, after.number, after.format, format)
    shown = (starting.format, starting.parts, starting.first_reply)
    same = [v.number for v in earlier if (v.format, v.parts, v.first_reply) == shown]
    if same:
        back_to = starting.version_number if starting.version_number in same else same[-1]
        # Only a first reply, which the model never sees, made the Text differ from this Version.
        if back_to == after.number:
            return feedback_message(feedback, after.number, after.format, format)
        return went_back_message(feedback, after.number, back_to, starting.format, format)
    began_from = None if starting.version_number == after.number else starting.version_number
    return changed_message(
        feedback,
        after.number,
        began_from,
        starting.format,
        starting.parts,
        format,
        first_reply=starting.first_reply,
    )


def revision_messages(
    corpus: Corpus,
    brief: str,
    earlier: Sequence[EarlierVersion],
    starting: Optional[StartingText],
    feedback: str,
    format: Format,
    char_limit: int,
) -> list[dict]:
    """The sketch call's conversation continued, under the new Format's prompt."""
    return sketch_messages(corpus, brief, format, char_limit) + replayed_versions(
        earlier, starting, feedback, format
    )


def replayed_versions(
    earlier: Sequence[EarlierVersion],
    starting: Optional[StartingText],
    feedback: str,
    format: Format,
) -> list[dict]:
    """
    Each Version's text in its own Format as the model's answer after the Feedback that asked for
    it, then the new Feedback, given on `starting` when the Text isn't the latest Version as
    written. Each Feedback names the Version before it and says what the User did to the Text, and
    one that switched Format says so. Sketches stay out: the User never reacted to them.
    """
    messages: list[dict] = []
    for index, version in enumerate(earlier):
        if index > 0 and version.feedback is not None:
            framed = _framed_feedback(
                version.feedback, earlier[:index], version.starting_text, version.format
            )
            messages.append(user_message(framed))
        content = format_text(version.format, version.parts, first_reply=version.first_reply)
        messages.append({"role": "assistant", "content": content})
    messages.append(user_message(_framed_feedback(feedback, earlier, starting, format)))
    return messages


def _usage(result: StructuredResult) -> Optional[dict]:
    return None if result.usage is None else result.usage.raw


def thread_parts(call: str, parts: list[str]) -> list[str]:
    """A Thread reply's Parts, or an `LLMError` that fails the attempt: a Thread is never cut."""
    if not THREAD_MIN_PARTS <= len(parts) <= THREAD_MAX_PARTS:
        raise LLMError(
            f"The {call} call wrote {len(parts)} Parts; "
            f"a Thread has {THREAD_MIN_PARTS} to {THREAD_MAX_PARTS}"
        )
    if any(not part.strip() for part in parts):
        raise LLMError(f"The {call} call wrote a blank Part")
    return parts


def _parts_of(call: str, reply: BaseModel) -> list[str]:
    """A single post's text as its one Part, or a Thread's Parts once checked."""
    if isinstance(reply, (WrittenThread, FinalThread)):
        return thread_parts(call, reply.parts)
    assert isinstance(reply, (WrittenPost, FinalPost))
    return [reply.post]


async def write_next_version(
    llm: LLM,
    corpus: Corpus,
    brief: str,
    earlier: Sequence[EarlierVersion],
    starting: Optional[StartingText],
    feedback: str,
    format: Format,
    char_limit: int,
) -> WrittenVersion:
    """
    Write the Version after `earlier` in `format`, from Feedback on `starting` or else the latest
    Version, for an X account whose posts hold up to
    `char_limit` characters. Raises whatever the LLM port raises, or an
    `LLMError` for a Thread of the wrong length; nothing is stored here.
    A first reply stays out of the calls: a single post keeps the one its Feedback was given on
    as it is, and a Thread ends with its text (ADR 0027). A blank one is dropped, as the single
    post writing drops one.
    """
    shown = earlier[-1] if starting is None else starting
    kept_reply = shown.parts[-1] if shown.first_reply and shown.parts[-1].strip() else None
    earlier = [_without_first_reply(v) for v in earlier]
    starting = _without_first_reply(starting) if starting is not None else None
    revised = await llm.structured(
        model=settings.LLM_REVISING_MODEL,
        messages=revision_messages(corpus, brief, earlier, starting, feedback, format, char_limit),
        response_model=_REVISED[format],
        max_tokens=MAX_TOKENS,
    )
    sketch_parts = [scrub(part) for part in _parts_of("revision", revised.parsed)]
    messages = revision_humanizer_messages(
        corpus, brief, earlier, starting, feedback, format, char_limit, sketch_parts
    )
    written = await _humanize(llm, format, messages, revised, sketch_parts, _hook(revised.parsed))
    if kept_reply is None:
        return written
    if format == FORMAT_THREAD:
        return replace(written, parts=_ending_with(written.parts, scrub(kept_reply), char_limit))
    return replace(written, parts=[*written.parts, kept_reply], first_reply=True)


def _ending_with(parts: list[str], text: str, char_limit: int) -> list[str]:
    """
    A Thread's Parts with `text` after its last Part, or as a Part of its own when the last has no
    room for it. A Thread with no Part to spare takes it over the limit, which is flagged, not refused.
    """
    joined = f"{parts[-1]}\n\n{text}"
    if x_weighted_length(joined) > char_limit and len(parts) < THREAD_MAX_PARTS:
        return [*parts, text]
    return [*parts[:-1], joined]


def _without_first_reply[T: (EarlierVersion, StartingText)](text: T) -> T:
    """`text` with no first reply, which the pumpkit-v6 prompts have no place for."""
    if isinstance(text, EarlierVersion) and text.starting_text is not None:
        text = replace(text, starting_text=_without_first_reply(text.starting_text))
    if not text.first_reply:
        return text
    return replace(text, parts=text.parts[:-1], first_reply=False)


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
    sketch_parts: list[str],
    hook: Hook,
) -> WrittenVersion:
    refined = await llm.structured(
        model=settings.LLM_HUMANIZING_MODEL,
        messages=messages,
        response_model=_FINAL[format],
        max_tokens=MAX_TOKENS,
    )
    parts = _parts_of("humanizer", refined.parsed)
    return WrittenVersion(
        format=format,
        sketch_parts=sketch_parts,
        parts=parts,
        sketch_model=written.model,
        humanizing_model=refined.model,
        sketch_usage=_usage(written),
        humanizing_usage=_usage(refined),
        hook=hook,
    )
