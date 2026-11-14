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
from pydantic import BaseModel, ValidationError

from pumpkit.core.errors import AppError
from pumpkit.core.llm_client import LLMClient, llm_client
from pumpkit.core.llm_schemas import ModelUsage, StructuredResult

T = TypeVar("T", bound=BaseModel)


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
    ) -> StructuredResult[T]: ...


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
    max_tokens: Optional[int] = None


@dataclass
class FakeLLM:
    """
    A scripted model: each call takes the reply `standing` holds for its schema name, or else the
    next of `replies`: a dict of fields or an exception. Clear `configured` for a missing key.
    """

    replies: list[Union[dict[str, Any], Exception]] = field(default_factory=list)
    standing: dict[str, Union[dict[str, Any], Exception]] = field(default_factory=dict)
    calls: list[LLMCall] = field(default_factory=list)
    configured: bool = True

    def is_configured(self) -> bool:
        return self.configured

    async def structured(
        self,
        *,
        model: str,
        messages: list[dict],
        response_model: type[T],
        max_tokens: Optional[int] = None,
    ) -> StructuredResult[T]:
        self.calls.append(
            LLMCall(
                model=model,
                messages=messages,
                response_model=response_model,
                max_tokens=max_tokens,
            )
        )
        if response_model.__name__ in self.standing:
            reply = self.standing[response_model.__name__]
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
