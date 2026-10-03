from __future__ import annotations

from typing import Any, AsyncGenerator, Literal, Optional, TypeVar

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.core.config import settings
from app.schemas.openrouter import (
    AssembledToolCall,
    CompleteResult,
    ModelUsage,
    StreamDelta,
    StreamEvent,
    StructuredResult,
    ToolCallDelta,
)

T = TypeVar("T", bound=BaseModel)

ReasoningEffort = Literal["low", "medium", "high"]

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

_LLM_CLIENT_TIMEOUT = httpx.Timeout(
    600.0,  # Timeout for read operations, write operations, and acquiring connection from pool
    connect=10.0,  # Timeout to establish a connection
)
_LLM_CLIENT_MAX_RETRIES = 2

class LLMNotConfiguredError(RuntimeError):
    """Raised when an LLM call is attempted without OPENROUTER_API_KEY configured."""


class OpenRouterClient:
    """
    Async wrapper around OpenRouter's OpenAI-compatible chat completions API.

    The underlying SDK client is created on first use, so the application boots
    without OPENROUTER_API_KEY; calling any method without it raises
    LLMNotConfiguredError.
    """

    def __init__(self) -> None:
        self._client: Optional[AsyncOpenAI] = None

    @property
    def _llm_client(self) -> AsyncOpenAI:
        if self._client is None:
            if not settings.OPENROUTER_API_KEY:
                raise LLMNotConfiguredError(
                    "OPENROUTER_API_KEY is not set. Add it to backend/.env to enable LLM calls."
                )
            self._client = AsyncOpenAI(
                api_key=settings.OPENROUTER_API_KEY,
                base_url=_OPENROUTER_BASE_URL,
                timeout=_LLM_CLIENT_TIMEOUT,
                max_retries=_LLM_CLIENT_MAX_RETRIES,
            )
        return self._client

    async def llm_complete(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        reasoning_effort: Optional[ReasoningEffort] = None,
        extra_body: Optional[dict] = None,
    ) -> CompleteResult:
        """
        Non-streamed, non-structured LLM call.

        Returns a `CompleteResult` carrying the generated text plus the
        upstream model name and (when the provider returns it) token usage.
        Callers decide what to do with those: log, trace, bill usage, etc.
        """
        kwargs = self._build_llm_kwargs(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            reasoning_effort=reasoning_effort,
            extra_body=extra_body,
        )
        response = await self._llm_client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""

        if not content:
            raise ValueError(
                f"OpenRouter returned an empty response for a non-streamed, non-structured LLM call. model={kwargs.get('model')}"
            )

        return CompleteResult(
            content=content,
            model=response.model,
            usage=self._extract_usage(response),
        )

    async def llm_stream(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        reasoning_effort: Optional[ReasoningEffort] = None,
        extra_body: Optional[dict] = None,
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[Any] = None,
    ) -> AsyncGenerator[StreamEvent, None]:
        """Streamed call. Yields StreamDelta for content, ToolCallDelta per
        fragment, AssembledToolCall once per completed tool call at round end,
        and ModelUsage at the end if the provider reports it.

        The `include_usage` option is always set: usage capture is required
        for cost tracking and observability and cannot be disabled by callers.
        """
        kwargs = self._build_llm_kwargs(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            reasoning_effort=reasoning_effort,
            extra_body=extra_body,
            tools=tools,
            tool_choice=tool_choice,
        )
        stream = await self._llm_client.chat.completions.create(
            stream=True,
            stream_options={"include_usage": True},
            **kwargs,
        )
        # index -> {"id", "name", "arguments"}
        pending: dict[int, dict] = {}
        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta
                content = getattr(delta, "content", None)
                if content:
                    yield StreamDelta(text=content)
                for frag in getattr(delta, "tool_calls", None) or []:
                    idx = frag.index
                    slot = pending.setdefault(idx, {"id": None, "name": None, "arguments": ""})
                    if frag.id:
                        slot["id"] = frag.id
                    fn = getattr(frag, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            slot["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            slot["arguments"] += fn.arguments
                    yield ToolCallDelta(
                        index=idx,
                        id=frag.id,
                        name=getattr(fn, "name", None) if fn else None,
                        arguments=getattr(fn, "arguments", "") if fn else "",
                    )
            usage = self._extract_usage(chunk)
            if usage is not None:
                yield usage
        for idx in sorted(pending):
            slot = pending[idx]
            if slot["id"] and slot["name"]:
                yield AssembledToolCall(
                    id=slot["id"], name=slot["name"], arguments=slot["arguments"]
                )

    async def llm_structured(
        self,
        *,
        model: str,
        messages: list[dict],
        response_model: type[T],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        reasoning_effort: Optional[ReasoningEffort] = None,
        extra_body: Optional[dict] = None,
    ) -> StructuredResult[T]:
        """
        Non-streamed, structured LLM call.

        Returns a `StructuredResult[T]` carrying the parsed Pydantic instance,
        the upstream model name, and (when the provider returns it) token usage.
        """
        kwargs = self._build_llm_kwargs(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            reasoning_effort=reasoning_effort,
            extra_body=extra_body,
        )
        response = await self._llm_client.beta.chat.completions.parse(
            response_format=response_model,
            **kwargs,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError(
                f"OpenRouter returned an empty response for a non-streamed, structured LLM call. response_model={response_model.__name__}, model={kwargs.get('model')}"
            )
        return StructuredResult(
            parsed=parsed,
            model=response.model,
            usage=self._extract_usage(response),
        )

    @staticmethod
    def _prune_none(d: dict) -> dict:
        """Return a copy of the given dict omitting key-value pairs where the value is `None`."""
        return {k: v for k, v in d.items() if v is not None}

    @staticmethod
    def _extract_usage(response_or_chunk: Any) -> Optional[ModelUsage]:
        """
        Extract a `ModelUsage` from any OpenAI SDK object that may carry a `usage` field.

        Works for both non-streamed responses (where usage is on the response object) and
        streaming chunks (where usage is populated on the final pre-`[DONE]` chunk).
        Returns `None` if the provider didn't include usage.
        """
        usage = getattr(response_or_chunk, "usage", None)
        if usage is None:
            return None
        usage_dict = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)
        return ModelUsage(
            prompt_tokens=usage_dict.get("prompt_tokens", 0),
            completion_tokens=usage_dict.get("completion_tokens", 0),
            total_tokens=usage_dict.get("total_tokens", 0),
            raw=usage_dict,
        )

    @staticmethod
    def _build_llm_kwargs(
        *,
        model: str,
        messages: list[dict],
        temperature: Optional[float],
        max_tokens: Optional[int],
        top_p: Optional[float],
        reasoning_effort: Optional[ReasoningEffort],
        extra_body: Optional[dict],
        tools: Optional[list[dict]] = None,
        tool_choice: Optional[Any] = None,
    ) -> dict:
        """
        Assemble kwargs for an LLM call through the OpenAI SDK.

        - `None` values are omitted from the request.
        - `reasoning_effort` is translated to OpenRouter's unified
          `reasoning: {effort: ...}` shape, merged into `extra_body`.
        - Caller's `extra_body` overrides wrapper-constructed keys.
        - `tools` is passed through when provided (non-None, non-empty).
        - `tool_choice` (e.g. "auto", "required", or a forced-function dict) is
          passed through when provided; only meaningful alongside `tools`.
        """
        wrapper_extra: dict = {}

        # Convert reasoning effort to OpenRouter's expected format.
        if reasoning_effort is not None:
            wrapper_extra["reasoning"] = {"effort": reasoning_effort}

        merged_extra = {**wrapper_extra, **(extra_body or {})}

        kwargs: dict = {"model": model, "messages": messages}

        if tools:
            kwargs["tools"] = tools
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice

        # Pass optional parameters only if they are not None,
        # so we don't override model defaults with None.
        kwargs.update(
            OpenRouterClient._prune_none(
                {
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "top_p": top_p,
                }
            )
        )

        if merged_extra:
            kwargs["extra_body"] = merged_extra

        return kwargs


openrouter_client = OpenRouterClient()
