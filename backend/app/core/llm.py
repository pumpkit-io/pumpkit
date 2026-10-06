"""
The `LLM` port: one structured-output call to a model.

Any provider failure, including an answer that doesn't fit the schema, is an `LLMError` (a 502
with an `error_id`); a missing key stays the client's `LLMNotConfiguredError` (a 503).

Mediators reach the model only through `get_llm`; tests override it with `FakeLLM`.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Optional, Protocol, TypeVar, Union

from openai import OpenAIError
from pydantic import BaseModel

from app.core.openrouter import OpenRouterClient, openrouter_client
from app.schemas.openrouter import ModelUsage, StructuredResult

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """A model call failed: network, provider error, or an answer that can't be read."""


class LLM(Protocol):
    async def structured(
        self,
        *,
        model: str,
        messages: list[dict],
        response_model: type[T],
        max_tokens: Optional[int] = None,
    ) -> StructuredResult[T]: ...


class OpenRouterLLM:
    def __init__(self, client: OpenRouterClient) -> None:
        self._client = client

    async def structured(
        self,
        *,
        model: str,
        messages: list[dict],
        response_model: type[T],
        max_tokens: Optional[int] = None,
    ) -> StructuredResult[T]:
        try:
            return await self._client.llm_structured(
                model=model, messages=messages, response_model=response_model, max_tokens=max_tokens
            )
        # ValueError covers an empty answer and one that fails the schema's validation.
        except (OpenAIError, ValueError) as error:
            raise LLMError(f"{model}: {type(error).__name__}: {error}") from error


@dataclass(frozen=True)
class LLMCall:
    model: str
    messages: list[dict]
    response_model: type[BaseModel]


@dataclass
class FakeLLM:
    """
    A scripted model: each call takes the next of `replies`, a dict of the response model's
    fields or an exception to raise, and is recorded in `calls`.
    """

    replies: list[Union[dict[str, Any], Exception]] = field(default_factory=list)
    calls: list[LLMCall] = field(default_factory=list)

    async def structured(
        self,
        *,
        model: str,
        messages: list[dict],
        response_model: type[T],
        max_tokens: Optional[int] = None,
    ) -> StructuredResult[T]:
        self.calls.append(LLMCall(model=model, messages=messages, response_model=response_model))
        if not self.replies:
            raise LLMError("Fake LLM has no reply left")
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
        return StructuredResult(
            parsed=response_model.model_validate(reply),
            model=model,
            usage=ModelUsage(**usage, raw=usage),
        )


@lru_cache
def get_llm() -> LLM:
    """FastAPI dependency for the `LLM` port."""
    return OpenRouterLLM(openrouter_client)
