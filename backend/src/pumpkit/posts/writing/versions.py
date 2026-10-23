"""
Writing a Version, the pumpkit-v6 way with a Hook written first: the Jev check on a Feedback
Version, the hook call (always on the first Version, after Feedback only when Jev asks for a new
Hook), the writing call (the draft call for the first Version, the revision call after
Feedback), told to start with the Hook when there is one, the scrub, then the humanizer call.

The scrubbed writing-call text is the Draft and the humanizer's text is the Final. Every call
gets the system prompt first and the corpus second, as in v6, so the per-call parts come after a
prefix that stays the same across a Post's Versions.
"""

from dataclasses import dataclass, replace
from typing import Any, Optional, Sequence

from pydantic import BaseModel, ConfigDict

from pumpkit.core.classifier import Classifier, ClassifierNotConfiguredError
from pumpkit.core.config import settings
from pumpkit.core.logging import logger
from pumpkit.posts.llm import LLM
from pumpkit.posts.llm_schemas import StructuredResult
from pumpkit.posts.writing.constants import CACHE_TTL, MAX_TOKENS
from pumpkit.posts.writing.corpus import Corpus
from pumpkit.posts.writing.hook import HookRefused, WrittenHook, usable_hook
from pumpkit.posts.writing.prompts.brief import brief_message
from pumpkit.posts.writing.prompts.corpus import context_message
from pumpkit.posts.writing.prompts.draft_post import DRAFT_POST_PROMPT
from pumpkit.posts.writing.prompts.feedback import feedback_message
from pumpkit.posts.writing.prompts.hook import (
    HOOK_PROMPT,
    hook_brief_message,
    hook_feedback_message,
    hook_previous_final_message,
    revision_start_with_hook_message,
    start_with_hook_message,
)
from pumpkit.posts.writing.prompts.hook_check import (
    HOOK_CHECK_QUESTION,
    HOOK_CHECK_QUESTION_NAME,
    NEW_HOOK,
)
from pumpkit.posts.writing.prompts.humanizer import HUMANIZER_PROMPT
from pumpkit.posts.writing.prompts.revision_humanizer import (
    latest_feedback_message,
    previous_final_message,
    revised_draft_message,
)
from pumpkit.posts.writing.scrub import scrub


class DraftedPost(BaseModel):
    # A single field leaves the model no room for commentary around the post.
    model_config = ConfigDict(extra="forbid")

    post: str


class FinalPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post: str


class RevisedPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post: str


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
class HookCheck:
    label: Optional[str] = None
    probabilities: Optional[dict[str, float]] = None
    model: Optional[str] = None


@dataclass(frozen=True)
class HookCall:
    name: Optional[str] = None
    text: Optional[str] = None
    followed: Optional[bool] = None
    model: Optional[str] = None
    usage: Optional[dict] = None
    answer: Optional[dict] = None


@dataclass(frozen=True)
class WrittenVersion:
    draft: str
    final: str
    writing_model: str
    humanizing_model: str
    writing_usage: Optional[dict]
    humanizing_usage: Optional[dict]
    hook: HookCall
    hook_check: HookCheck


def _system(prompt: str) -> dict:
    # The only cache breakpoint, as in v6: the system prompt is what every call of every Post shares.
    cache_control = {"type": "ephemeral", "ttl": CACHE_TTL}
    return {
        "role": "system",
        "content": [{"type": "text", "text": prompt, "cache_control": cache_control}],
    }


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


def draft_messages(corpus: Corpus, brief: str, hook: Optional[str] = None) -> list[dict]:
    messages = [_system(DRAFT_POST_PROMPT), _user(context_message(corpus)), _user(brief)]
    if hook is not None:
        messages.append(_user(start_with_hook_message(hook)))
    return messages


def hook_messages(corpus: Corpus, brief: str) -> list[dict]:
    return [_system(HOOK_PROMPT), _user(context_message(corpus)), _user(hook_brief_message(brief))]


def revision_hook_messages(
    corpus: Corpus, brief: str, previous_final: str, feedback: str
) -> list[dict]:
    """Earlier Feedback stays out: the previous Final already applies it."""
    return [
        *hook_messages(corpus, brief),
        _user(hook_previous_final_message(previous_final)),
        _user(hook_feedback_message(feedback)),
    ]


def hook_check_state(
    brief: str, earlier: Sequence[EarlierVersion], feedback: str
) -> dict[str, Any]:
    """
    What Jev reads: the conversation the User saw, before anything is written from the latest
    Feedback. The corpus and earlier Drafts stay out, as nothing in them tells whether the User
    asked for the opening.
    """
    conversation = [{"from": "user", "text": brief}]
    for version in earlier:
        if version.feedback is not None:
            conversation.append({"from": "user", "text": version.feedback})
        conversation.append({"from": "pumpkit", "text": version.final})
    conversation.append({"from": "user", "text": feedback})
    return {"conversation": conversation}


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
    hook: Optional[str] = None,
) -> list[dict]:
    """
    The draft call's conversation continued: the Brief, each Final as the model's answer after
    the Feedback that asked for it, then the new Feedback and the new Hook. Drafts and earlier
    Hooks stay out: the User never reacted to them, and each Final opens with its Hook.
    """
    messages = [_system(DRAFT_POST_PROMPT), _user(context_message(corpus)), _user(brief)]
    for version in earlier:
        if version.feedback is not None:
            messages.append(_user(feedback_message(version.feedback)))
        messages.append({"role": "assistant", "content": version.final})
    messages.append(_user(feedback_message(feedback)))
    if hook is not None:
        messages.append(_user(revision_start_with_hook_message(hook)))
    return messages


def _usage(result: StructuredResult) -> Optional[dict]:
    return None if result.usage is None else result.usage.raw


async def write_first_version(llm: LLM, corpus: Corpus, brief: str) -> WrittenVersion:
    """Raises whatever the LLM port raises; nothing is stored here."""
    hook = await _hook(llm, hook_messages(corpus, brief))
    drafted = await llm.structured(
        model=settings.LLM_DRAFTING_MODEL,
        messages=draft_messages(corpus, brief, hook.text),
        response_model=DraftedPost,
        max_tokens=MAX_TOKENS,
    )
    hook = _check_followed(hook, drafted.parsed.post)
    draft = scrub(drafted.parsed.post)
    messages = humanizer_messages(corpus, brief, draft)
    return await _humanize(llm, messages, drafted, draft, hook, HookCheck())


async def _hook(llm: LLM, messages: list[dict]) -> HookCall:
    """
    The hook call's record, whose text is None when there is no Hook. Never raises: a Hook is
    worth less than the Version, so any failure writes the Version without one.
    """
    try:
        written = await llm.structured(
            model=settings.LLM_HOOKING_MODEL,
            messages=messages,
            response_model=WrittenHook,
            max_tokens=MAX_TOKENS,
        )
    except Exception:
        logger.exception("Hook call failed, the Version is written without a Hook")
        return HookCall()
    answer = written.parsed.model_dump()
    try:
        hook = usable_hook(written.parsed)
    except HookRefused as refusal:
        logger.warning("Hook call failed, the Version is written without a Hook: %s", refusal)
        return HookCall(answer=answer)
    return HookCall(
        name=written.parsed.hook_name,
        text=hook,
        model=written.model,
        usage=_usage(written),
        answer=answer,
    )


def _check_followed(hook: HookCall, written: str) -> HookCall:
    """Checked before the scrub, which may change the Hook's punctuation."""
    if hook.text is None:
        return hook
    followed = written.lstrip().startswith(hook.text)
    if not followed:
        logger.warning("The writing call's text doesn't start with the Hook it was given")
    return replace(hook, followed=followed)


async def _check_hook(classifier: Classifier, state: dict[str, Any]) -> HookCheck:
    """Never raises: without Jev's answer the hook call is skipped, so no opening is overwritten."""
    try:
        classification = await classifier.classify(
            state=state,
            questions={HOOK_CHECK_QUESTION_NAME: HOOK_CHECK_QUESTION},
            model=settings.TYPESAFE_MODEL,
        )
    except ClassifierNotConfiguredError:
        logger.info("Jev is not configured, the Feedback Version keeps its opening")
        return HookCheck()
    except Exception:
        logger.exception("Jev check failed, the Feedback Version keeps its opening")
        return HookCheck()
    answer = classification.answers[HOOK_CHECK_QUESTION_NAME]
    return HookCheck(
        label=answer.choice, probabilities=answer.probabilities, model=classification.model
    )


async def write_next_version(
    llm: LLM,
    classifier: Classifier,
    corpus: Corpus,
    brief: str,
    earlier: Sequence[EarlierVersion],
    feedback: str,
) -> WrittenVersion:
    """Raises whatever the LLM port raises; nothing is stored here."""
    check = await _check_hook(classifier, hook_check_state(brief, earlier, feedback))
    # No confidence threshold: the top label decides.
    if check.label == NEW_HOOK:
        messages = revision_hook_messages(corpus, brief, earlier[-1].final, feedback)
        hook = await _hook(llm, messages)
    else:
        hook = HookCall()
    revised = await llm.structured(
        model=settings.LLM_REVISING_MODEL,
        messages=revision_messages(corpus, brief, earlier, feedback, hook.text),
        response_model=RevisedPost,
        max_tokens=MAX_TOKENS,
    )
    hook = _check_followed(hook, revised.parsed.post)
    draft = scrub(revised.parsed.post)
    messages = revision_humanizer_messages(corpus, brief, earlier[-1].final, feedback, draft)
    return await _humanize(llm, messages, revised, draft, hook, check)


async def _humanize(
    llm: LLM,
    messages: list[dict],
    written: StructuredResult,
    draft: str,
    hook: HookCall,
    hook_check: HookCheck,
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
        hook_check=hook_check,
    )
