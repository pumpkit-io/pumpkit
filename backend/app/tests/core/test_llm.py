import json
from typing import Any

import httpx
import pytest
import respx
from pydantic import BaseModel, ConfigDict

from app.core.llm import LLMError, OpenRouterLLM
from app.core.openrouter import OpenRouterClient

COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post: str


def _completion(content: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "openai/gpt-5.6-luna",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


@respx.mock
async def test_a_structured_call_reaches_openrouter_and_comes_back_parsed():
    sent: dict[str, Any] = {}

    def _respond(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(200, json=_completion(json.dumps({"post": "hello"})))

    respx.post(COMPLETIONS_URL).mock(side_effect=_respond)
    messages = [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}]

    result = await OpenRouterLLM(OpenRouterClient()).structured(
        model="openai/gpt-5.6-luna", messages=messages, response_model=_Answer, max_tokens=500
    )

    assert result.parsed == _Answer(post="hello")
    assert result.model == "openai/gpt-5.6-luna"
    assert result.usage is not None and result.usage.total_tokens == 120
    assert sent["messages"] == messages
    assert sent["max_tokens"] == 500
    assert sent["response_format"]["json_schema"]["name"] == "_Answer"


@respx.mock
async def test_a_provider_error_becomes_an_llm_error():
    respx.post(COMPLETIONS_URL).mock(
        return_value=httpx.Response(400, json={"error": {"message": "bad request"}})
    )

    with pytest.raises(LLMError):
        await OpenRouterLLM(OpenRouterClient()).structured(
            model="m", messages=[{"role": "user", "content": "x"}], response_model=_Answer
        )


@respx.mock
async def test_an_answer_that_does_not_fit_the_schema_becomes_an_llm_error():
    respx.post(COMPLETIONS_URL).mock(
        return_value=httpx.Response(200, json=_completion(json.dumps({"text": "hello"})))
    )

    with pytest.raises(LLMError):
        await OpenRouterLLM(OpenRouterClient()).structured(
            model="m", messages=[{"role": "user", "content": "x"}], response_model=_Answer
        )


@respx.mock
async def test_a_cache_breakpoint_reaches_openrouter_and_cached_tokens_come_back_in_usage():
    sent: dict[str, Any] = {}
    reported = {
        "prompt_tokens": 1000,
        "completion_tokens": 20,
        "total_tokens": 1020,
        "prompt_tokens_details": {"cached_tokens": 900, "cache_write_tokens": 0},
        "cost": 0.0004,
    }

    def _respond(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        completion = _completion(json.dumps({"post": "hello"}))
        completion["usage"] = reported
        return httpx.Response(200, json=completion)

    respx.post(COMPLETIONS_URL).mock(side_effect=_respond)
    block = {
        "type": "text",
        "text": "be brief",
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
    }
    messages = [{"role": "system", "content": [block]}, {"role": "user", "content": "hi"}]

    result = await OpenRouterLLM(OpenRouterClient()).structured(
        model="m", messages=messages, response_model=_Answer
    )

    assert sent["messages"][0]["content"] == [block]
    assert result.usage is not None
    assert result.usage.raw["prompt_tokens_details"]["cached_tokens"] == 900
    assert result.usage.raw["prompt_tokens_details"]["cache_write_tokens"] == 0
