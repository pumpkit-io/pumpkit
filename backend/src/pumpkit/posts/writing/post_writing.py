"""
Writing a single post's Versions from its Plan, as pumpkit-new-architecture-v5 does (ADR 0026).
The first: sketches in parallel, each trying a different hook type first, then the merge, the
scrub, the humanizer and the scrub again; the merged sketch, scrubbed, is the Version's Sketch.
After Feedback: the revise call, the scrub, the revision humanizer and the scrub again; the
revised post, scrubbed, is the Sketch.
"""

import asyncio
import logging
from typing import Any, Optional, Sequence, TypeVar, Union

from pydantic import BaseModel

from pumpkit.core.config import settings
from pumpkit.core.llm import LLM, LLMError
from pumpkit.core.llm_schemas import StructuredResult
from pumpkit.core.text import drop_unstorable
from pumpkit.posts.formats import FORMAT_POST, FORMAT_THREAD, Format
from pumpkit.posts.plans import Plan
from pumpkit.posts.writing.constants import MAX_TOKENS, SKETCHES_PER_POST
from pumpkit.posts.writing.corpus import Corpus
from pumpkit.posts.writing.post_replies import (
    HookType,
    HumanizedPost,
    MergedSketch,
    RevisedPost,
    SketchedPost,
)
from pumpkit.posts.writing.prompts.post import (
    PostInputs,
    brief_message,
    humanizer_prompt,
    merge_prompt,
    merge_user,
    post_inputs_block,
    post_message,
    sketch_angle,
    sketch_prompt,
    sketch_user,
)
from pumpkit.posts.writing.prompts.revise import (
    previous_post_message,
    revise_prompt,
    revised_post_message,
)
from pumpkit.posts.writing.prompts.revision_humanizer import (
    earlier_feedback_message,
    hand_written_message,
    latest_feedback_message,
)
from pumpkit.posts.writing.scrub import scrub
from pumpkit.posts.writing.starting_text import StartingText
from pumpkit.posts.writing.versions import (
    EarlierVersion,
    Hook,
    WrittenVersion,
    hand_written,
    replayed_versions,
    system_message,
    user_message,
    write_first_version,
    write_next_version,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# The request waits on the writing, so each call gets this long once sent, then counts as failed.
WRITING_CALL_SECONDS = 240.0


def _clean(text: str) -> str:
    return drop_unstorable(scrub(text)).strip()


def _storable(value: Any) -> Any:
    """`value` with every string fit for a Postgres JSONB column."""
    if isinstance(value, str):
        return drop_unstorable(value)
    if isinstance(value, list):
        return [_storable(item) for item in value]
    if isinstance(value, dict):
        return {key: _storable(item) for key, item in value.items()}
    return value


def _with_first_reply(post: str, first_reply: Optional[str], *, kept: bool) -> list[str]:
    """
    The post, then its first reply when the humanizer kept one. A reply it made up for a post that
    had none is dropped, as in v5, and so is one the scrub leaves blank.
    """
    reply = _clean(first_reply) if first_reply and kept else ""
    return [post, reply] if reply else [post]


def _usage(result: StructuredResult) -> Optional[dict]:
    return None if result.usage is None else result.usage.raw


async def _call(
    llm: LLM, model: str, messages: list[dict], response_model: type[T]
) -> StructuredResult[T]:
    return await llm.structured(
        model=model,
        messages=messages,
        response_model=response_model,
        max_tokens=MAX_TOKENS,
        timeout_seconds=WRITING_CALL_SECONDS,
    )


async def _sketches(
    llm: LLM, inputs: PostInputs, user_id: str
) -> tuple[list[SketchedPost], list[dict]]:
    """The sketches that succeeded, in the order they were asked for, and a record of every call."""
    model = settings.LLM_SKETCHING_MODEL
    # One system prompt for every sketch, so they share one cache entry.
    system = system_message(sketch_prompt(inputs))

    async def sketch(angle: HookType) -> StructuredResult[SketchedPost]:
        messages = [system, user_message(sketch_user(inputs, angle))]
        return await _call(llm, model, messages, SketchedPost)

    angles: list[HookType] = [sketch_angle(index) for index in range(SKETCHES_PER_POST)]
    results: list[Union[StructuredResult[SketchedPost], BaseException]] = await asyncio.gather(
        *(sketch(angle) for angle in angles), return_exceptions=True
    )
    # Only a failed model call is skipped; anything else, a missing key included, fails the write.
    for result in results:
        if isinstance(result, BaseException) and not isinstance(result, LLMError):
            raise result

    sketches: list[SketchedPost] = []
    records: list[dict] = []
    for number, (angle, result) in enumerate(zip(angles, results), start=1):
        if isinstance(result, BaseException):
            logger.warning(
                "Sketch %d of %d (angle %s) failed for User %s, skipped: %s",
                number,
                SKETCHES_PER_POST,
                angle,
                user_id,
                result,
            )
            records.append({"number": number, "angle": angle, "model": model, "error": str(result)})
            continue
        sketches.append(result.parsed)
        records.append(
            {
                "number": number,
                # The number the merge reads it under: failed sketches leave no gap.
                "merge_number": len(sketches),
                "angle": angle,
                "model": result.model,
                "usage": _usage(result),
                **result.parsed.model_dump(),
            }
        )
    if not sketches:
        raise LLMError(f"Every sketch call failed; the first: {results[0]}")
    return sketches, records


async def write_post(llm: LLM, inputs: PostInputs, *, user_id: str) -> WrittenVersion:
    """
    Write a single post's first Version. Raises an `LLMError` when every sketch call or the
    merge or humanizer call fails or writes a blank post, or whatever else the LLM port raises;
    stores nothing.
    """
    sketches, sketch_records = await _sketches(llm, inputs, user_id)

    merged = await _call(
        llm,
        settings.LLM_MERGING_MODEL,
        [
            system_message(merge_prompt(inputs, len(sketches))),
            user_message(merge_user(inputs, sketches)),
        ],
        MergedSketch,
    )
    merged_post = _clean(merged.parsed.post)
    if not merged_post:
        raise LLMError("The merge call wrote a blank post")
    merged_reply = _clean(merged.parsed.first_reply) if merged.parsed.first_reply else None

    humanized = await _call(
        llm,
        settings.LLM_HUMANIZING_MODEL,
        [
            system_message(humanizer_prompt(inputs)),
            user_message(brief_message(inputs)),
            user_message(post_message(merged_post, merged_reply)),
        ],
        HumanizedPost,
    )
    post = _clean(humanized.parsed.post)
    if not post:
        raise LLMError("The humanizer call wrote a blank post")
    parts = _with_first_reply(post, humanized.parsed.first_reply, kept=bool(merged_reply))

    return WrittenVersion(
        format=FORMAT_POST,
        sketch_parts=[merged_post, merged_reply] if merged_reply else [merged_post],
        parts=parts,
        sketch_model=merged.model,
        humanizing_model=humanized.model,
        sketch_usage=_usage(merged),
        humanizing_usage=_usage(humanized),
        hook_levers=list(merged.parsed.hook_levers),
        hook_types=list(merged.parsed.hook_types),
        cta_type=merged.parsed.cta_type,
        sketches=_storable(sketch_records),
        merge=_storable(
            {
                "reviews": [review.model_dump() for review in merged.parsed.reviews],
                "reasoning": merged.parsed.reasoning,
                "first_reply": merged_reply,
            }
        ),
        first_reply=len(parts) > 1,
    )


async def write_planned_version(
    llm: LLM,
    *,
    corpus: Corpus,
    brief: str,
    positioning: str,
    plan: Plan,
    format: Format,
    char_limit: int,
    user_id: str,
) -> WrittenVersion:
    """A Post's first Version in `format`: a Thread from the corpus, a single post from its Plan."""
    if format == FORMAT_THREAD:
        return await write_first_version(llm, corpus, brief, format, char_limit)
    inputs = PostInputs(brief=brief, positioning=positioning, plan=plan, char_limit=char_limit)
    return await write_post(llm, inputs, user_id=user_id)


def revision_inputs(
    *,
    brief: str,
    positioning: Optional[str],
    plan: Optional[Plan],
    text_format: Format,
    format: Format,
    char_limit: int,
) -> Optional[PostInputs]:
    """
    What the revise call writes Feedback from, or None when the Feedback is written the pumpkit-v6
    way: on a Thread either side of it, or on a Post planned without a single post's Plan.
    """
    if positioning is None or plan is None or plan.format != FORMAT_POST:
        return None
    if text_format != FORMAT_POST or format != FORMAT_POST:
        return None
    return PostInputs(brief=brief, positioning=positioning, plan=plan, char_limit=char_limit)


def revise_messages(
    inputs: PostInputs,
    earlier: Sequence[EarlierVersion],
    starting: Optional[StartingText],
    feedback: str,
) -> list[dict]:
    """v5's revise conversation, with Pumpkit's Feedback framings: Versions and Feedback only."""
    return [
        system_message(revise_prompt(inputs)),
        user_message(post_inputs_block(inputs)),
        *replayed_versions(earlier, starting, feedback, FORMAT_POST),
    ]


def revision_humanizer_messages(
    inputs: PostInputs,
    earlier: Sequence[EarlierVersion],
    starting: Optional[StartingText],
    feedback: str,
    revised: tuple[str, Optional[str]],
) -> list[dict]:
    """
    v5's revision humanizer, plus Pumpkit's message of the sentences the User wrote by hand. The
    post the Feedback was given on is the Starting text, or else the latest Version.
    """
    shown = earlier[-1] if starting is None else starting
    previous = shown.parts[0]
    first_reply = shown.parts[-1] if shown.first_reply else None
    messages = [
        system_message(humanizer_prompt(inputs)),
        user_message(brief_message(inputs)),
    ]
    earlier_feedback = [v.feedback for v in earlier if v.feedback is not None]
    if earlier_feedback:
        messages.append(user_message(earlier_feedback_message(earlier_feedback)))
    messages.append(user_message(previous_post_message(previous, first_reply)))
    messages.append(user_message(latest_feedback_message(feedback, FORMAT_POST, FORMAT_POST)))
    written_by_hand = hand_written(earlier, starting)
    if written_by_hand:
        messages.append(user_message(hand_written_message(written_by_hand, FORMAT_POST)))
    messages.append(user_message(revised_post_message(*revised)))
    return messages


async def revise_post(
    llm: LLM,
    inputs: PostInputs,
    earlier: Sequence[EarlierVersion],
    starting: Optional[StartingText],
    feedback: str,
) -> WrittenVersion:
    """
    Write a single post's next Version from Feedback on `starting`, or else the latest Version.
    Raises an `LLMError` when either call fails or writes a blank post; stores nothing.
    """
    revised = await _call(
        llm,
        settings.LLM_REVISING_MODEL,
        revise_messages(inputs, earlier, starting, feedback),
        RevisedPost,
    )
    revised_post = _clean(revised.parsed.post)
    if not revised_post:
        raise LLMError("The revise call wrote a blank post")
    revised_reply = _clean(revised.parsed.first_reply) if revised.parsed.first_reply else None

    humanized = await _call(
        llm,
        settings.LLM_HUMANIZING_MODEL,
        revision_humanizer_messages(
            inputs, earlier, starting, feedback, (revised_post, revised_reply)
        ),
        HumanizedPost,
    )
    post = _clean(humanized.parsed.post)
    if not post:
        raise LLMError("The revision humanizer call wrote a blank post")
    parts = _with_first_reply(post, humanized.parsed.first_reply, kept=bool(revised_reply))

    return WrittenVersion(
        format=FORMAT_POST,
        sketch_parts=[revised_post, revised_reply] if revised_reply else [revised_post],
        parts=parts,
        sketch_model=revised.model,
        humanizing_model=humanized.model,
        sketch_usage=_usage(revised),
        humanizing_usage=_usage(humanized),
        hook=Hook(reasoning=drop_unstorable(revised.parsed.reasoning), name=None),
        cta_type=revised.parsed.cta_type,
        first_reply=len(parts) > 1,
    )


async def write_planned_next_version(
    llm: LLM,
    *,
    inputs: Optional[PostInputs],
    corpus: Corpus,
    brief: str,
    earlier: Sequence[EarlierVersion],
    starting: Optional[StartingText],
    feedback: str,
    format: Format,
    char_limit: int,
) -> WrittenVersion:
    """The Version after `earlier`: by the revise call from `inputs`, or else from the corpus."""
    if inputs is None:
        return await write_next_version(
            llm, corpus, brief, earlier, starting, feedback, format, char_limit
        )
    return await revise_post(llm, inputs, earlier, starting, feedback)
