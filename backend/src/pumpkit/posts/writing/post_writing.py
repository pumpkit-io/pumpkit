"""
Writing a single post's first Version from its Plan, as pumpkit-new-architecture-v5 does: sketches
in parallel, each trying a different hook type first, then the merge, the scrub, the humanizer and
the scrub again (ADR 0026). The merged sketch, scrubbed, is the Version's Sketch.
"""

import asyncio
import logging
from typing import Any, Optional, TypeVar, Union

from pydantic import BaseModel

from pumpkit.core.config import settings
from pumpkit.core.llm import LLM, LLMError
from pumpkit.core.llm_schemas import StructuredResult
from pumpkit.core.text import drop_unstorable
from pumpkit.posts.formats import FORMAT_POST
from pumpkit.posts.writing.constants import CACHE_TTL, MAX_TOKENS, SKETCHES_PER_POST
from pumpkit.posts.writing.post_replies import HookType, HumanizedPost, MergedSketch, SketchedPost
from pumpkit.posts.writing.prompts.post import (
    PostInputs,
    brief_message,
    humanizer_prompt,
    merge_prompt,
    merge_user,
    post_message,
    sketch_angle,
    sketch_prompt,
    sketch_user,
)
from pumpkit.posts.writing.scrub import scrub
from pumpkit.posts.writing.versions import WrittenVersion

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# The request waits on the writing, so each call gets this long before it counts as failed.
WRITING_CALL_SECONDS = 240.0


def _system(prompt: str) -> dict:
    # The five sketch calls send the same system prompt, so they share one cache entry.
    cache_control = {"type": "ephemeral", "ttl": CACHE_TTL}
    return {
        "role": "system",
        "content": [{"type": "text", "text": prompt, "cache_control": cache_control}],
    }


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


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


def _usage(result: StructuredResult) -> Optional[dict]:
    return None if result.usage is None else result.usage.raw


async def _call(
    llm: LLM, step: str, model: str, messages: list[dict], response_model: type[T]
) -> StructuredResult[T]:
    try:
        async with asyncio.timeout(WRITING_CALL_SECONDS):
            return await llm.structured(
                model=model,
                messages=messages,
                response_model=response_model,
                max_tokens=MAX_TOKENS,
            )
    except TimeoutError as error:
        raise LLMError(f"{model}: the {step} call took over {WRITING_CALL_SECONDS:.0f}s") from error


async def _sketches(
    llm: LLM, inputs: PostInputs, user_id: str
) -> tuple[list[SketchedPost], list[dict]]:
    """The sketches that succeeded, in the order they were asked for, and a record of every call."""
    model = settings.LLM_SKETCHING_MODEL
    system = _system(sketch_prompt(inputs))

    async def sketch(angle: HookType) -> StructuredResult[SketchedPost]:
        messages = [system, _user(sketch_user(inputs, angle))]
        return await _call(llm, "sketch", model, messages, SketchedPost)

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
    merge or humanizer call fails, or whatever else the LLM port raises; stores nothing.
    """
    sketches, sketch_records = await _sketches(llm, inputs, user_id)

    merged = await _call(
        llm,
        "merge",
        settings.LLM_MERGING_MODEL,
        [
            _system(merge_prompt(inputs, len(sketches))),
            _user(merge_user(inputs, sketches)),
        ],
        MergedSketch,
    )
    merged_post = _clean(merged.parsed.post)
    merged_reply = _clean(merged.parsed.first_reply) if merged.parsed.first_reply else None

    humanized = await _call(
        llm,
        "humanizer",
        settings.LLM_HUMANIZING_MODEL,
        [
            _system(humanizer_prompt(inputs)),
            _user(brief_message(inputs)),
            _user(post_message(merged_post, merged_reply)),
        ],
        HumanizedPost,
    )
    post = _clean(humanized.parsed.post)
    if not post:
        raise LLMError("The humanizer call wrote a blank post")
    # A reply the humanizer made up for a post that had none is dropped, as in v5.
    first_reply = (
        _clean(humanized.parsed.first_reply)
        if humanized.parsed.first_reply and merged_reply
        else None
    )

    return WrittenVersion(
        format=FORMAT_POST,
        sketch_parts=[merged_post],
        parts=[post],
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
        first_reply=first_reply or None,
    )
