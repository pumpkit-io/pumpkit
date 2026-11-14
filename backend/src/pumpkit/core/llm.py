"""
The `LLM` port: one structured-output call to a model.

Any provider failure, including an answer that doesn't fit the schema, is an `LLMError` (a 502
with an `error_id`); a missing key stays the client's `LLMNotConfiguredError` (a 503).

Mediators reach the model only through `get_llm`; tests override it with `FakeLLM`.
"""

import asyncio
import weakref
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Awaitable, Callable, Optional, Protocol, TypeVar, Union

from openai import OpenAIError
from pydantic import BaseModel, ValidationError

from pumpkit.core.config import settings
from pumpkit.core.errors import AppError
from pumpkit.core.llm_client import LLMClient, llm_client
from pumpkit.core.llm_schemas import ModelUsage, StructuredResult

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")


class LLMError(AppError):
    """A model call failed: network, provider error, or an answer that can't be read."""

    status_code = 502
    public_detail = "Writing the post failed. Please try again."
    reported = True


class LLM(Protocol):
    def is_configured(self) -> bool:
        """Whether a model can be called at all; False makes every call raise the client's error."""
        ...

    async def structured(
        self,
        *,
        model: str,
        messages: list[dict],
        response_model: type[T],
        max_tokens: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> StructuredResult[T]:
        """
        One call, made once a slot under `LLM_CALLS_IN_FLIGHT` is free. `timeout_seconds` starts
        once the slot is held, so time spent waiting for one never counts against the call.
        """
        ...


# One per event loop: a semaphore can't be shared across loops, and each test runs its own.
_in_flight: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)


def _call_slots() -> asyncio.Semaphore:
    """The Instance's cap on model calls in flight, `LLM_CALLS_IN_FLIGHT`, shared by every call."""
    loop = asyncio.get_running_loop()
    slots = _in_flight.get(loop)
    if slots is None:
        slots = _in_flight[loop] = asyncio.Semaphore(settings.LLM_CALLS_IN_FLIGHT)
    return slots


async def _in_a_slot(
    model: str, timeout_seconds: Optional[float], call: Callable[[], Awaitable[R]]
) -> R:
    async with _call_slots():
        try:
            async with asyncio.timeout(timeout_seconds):
                return await call()
        except TimeoutError as error:
            raise LLMError(f"{model}: the call took over {timeout_seconds:.0f}s") from error


class OpenAICompatibleLLM:
    def __init__(self, client: LLMClient) -> None:
        self._client = client

    def is_configured(self) -> bool:
        return self._client.is_configured()

    async def structured(
        self,
        *,
        model: str,
        messages: list[dict],
        response_model: type[T],
        max_tokens: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> StructuredResult[T]:
        try:
            return await _in_a_slot(
                model,
                timeout_seconds,
                lambda: self._client.llm_structured(
                    model=model,
                    messages=messages,
                    response_model=response_model,
                    max_tokens=max_tokens,
                ),
            )
        # ValueError covers an empty answer and one that fails the schema's validation.
        except (OpenAIError, ValueError) as error:
            raise LLMError(f"{model}: {type(error).__name__}: {error}") from error


_Reply = Union[dict[str, Any], Exception]


@dataclass(frozen=True)
class LLMCall:
    model: str
    messages: list[dict]
    response_model: type[BaseModel]
    max_tokens: Optional[int] = None


@dataclass
class FakeLLM:
    """
    A scripted model: each call takes the reply `standing` holds for its schema class or name, or
    else the next of `replies`: a dict of fields or an exception. A standing reply can also be a
    function of the call, for calls that run in parallel. Each call holds a slot under the
    Instance's cap for `latency` seconds, as a real one does. A call whose schema `held` names
    first waits for that event to be set. Clear `configured` for a missing key.
    """

    replies: list[_Reply] = field(default_factory=list)
    standing: dict[Union[str, type[BaseModel]], Union[_Reply, Callable[["LLMCall"], _Reply]]] = (
        field(default_factory=dict)
    )
    calls: list[LLMCall] = field(default_factory=list)
    configured: bool = True
    latency: float = 0.0
    held: dict[Union[str, type[BaseModel]], asyncio.Event] = field(default_factory=dict)

    def is_configured(self) -> bool:
        return self.configured

    async def structured(
        self,
        *,
        model: str,
        messages: list[dict],
        response_model: type[T],
        max_tokens: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> StructuredResult[T]:
        call = LLMCall(
            model=model, messages=messages, response_model=response_model, max_tokens=max_tokens
        )
        self.calls.append(call)
        return await _in_a_slot(model, timeout_seconds, lambda: self._answer(call))

    async def _answer(self, call: LLMCall) -> StructuredResult[Any]:
        model, response_model = call.model, call.response_model
        hold = self.held.get(response_model) or self.held.get(response_model.__name__)
        if hold is not None:
            await hold.wait()
        if self.latency:
            await asyncio.sleep(self.latency)
        # A class key tells apart two schemas the model reads under one name.
        key = response_model if response_model in self.standing else response_model.__name__
        if key in self.standing:
            standing = self.standing[key]
            reply = standing(call) if callable(standing) else standing
        elif not self.replies:
            raise LLMError("Fake LLM has no reply left")
        else:
            reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        try:
            parsed = response_model.model_validate(reply)
        except ValidationError as error:
            raise LLMError(f"{model}: {type(error).__name__}: {error}") from error
        usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        return StructuredResult(
            parsed=parsed,
            model=model,
            usage=ModelUsage(**usage, raw=usage),
        )


@lru_cache
def get_llm() -> LLM:
    """FastAPI dependency for the `LLM` port."""
    return OpenAICompatibleLLM(llm_client)
