"""
What writing a Version from Feedback shares between a single post and a Thread: the Versions a
Post had, the Version written, the messages' shape, and the replay of earlier Versions with
Pumpkit's Feedback framings (ADR 0016).
"""

from dataclasses import dataclass
from typing import Optional, Sequence

from pumpkit.core.llm import LLMError
from pumpkit.posts.formats import Format
from pumpkit.posts.writing.constants import CACHE_TTL, THREAD_MAX_PARTS, THREAD_MIN_PARTS
from pumpkit.posts.writing.prompts.feedback import (
    changed_message,
    feedback_message,
    went_back_message,
)
from pumpkit.posts.writing.prompts.parts import format_text
from pumpkit.posts.writing.starting_text import StartingText, hand_written_sentences


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
    # Always None now: only the removed v6 writing set a library Hook's name; old Versions keep theirs.
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
    # The revise call's reasoning on a Version written from Feedback; None on a first Version.
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
        # Only a blank first reply, which counts as none, made the Text differ from this Version.
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
