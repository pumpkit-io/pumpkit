import asyncio
import json
from typing import Any

import httpx
import pytest
import respx
from pydantic import BaseModel, ConfigDict

from pumpkit.core.config import settings
from pumpkit.core.llm import FakeLLM, LLMError, OpenAICompatibleLLM
from pumpkit.core.llm_client import LLMClient

COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
LOCAL_BASE_URL = "http://localhost:11434/v1"


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

    result = await OpenAICompatibleLLM(LLMClient()).structured(
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
        await OpenAICompatibleLLM(LLMClient()).structured(
            model="m", messages=[{"role": "user", "content": "x"}], response_model=_Answer
        )


@respx.mock
async def test_an_answer_that_does_not_fit_the_schema_becomes_an_llm_error():
    respx.post(COMPLETIONS_URL).mock(
        return_value=httpx.Response(200, json=_completion(json.dumps({"text": "hello"})))
    )

    with pytest.raises(LLMError):
        await OpenAICompatibleLLM(LLMClient()).structured(
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

    result = await OpenAICompatibleLLM(LLMClient()).structured(
        model="m", messages=messages, response_model=_Answer
    )

    assert sent["messages"][0]["content"] == [block]
    assert result.usage is not None
    assert result.usage.raw["prompt_tokens_details"]["cached_tokens"] == 900
    assert result.usage.raw["prompt_tokens_details"]["cache_write_tokens"] == 0


@respx.mock
async def test_a_call_goes_to_the_configured_endpoint_with_the_configured_key(monkeypatch):
    monkeypatch.setattr(settings, "LLM_BASE_URL", LOCAL_BASE_URL)
    monkeypatch.setattr(settings, "LLM_API_KEY", "local-key")
    sent: dict[str, Any] = {}

    def _respond(request: httpx.Request) -> httpx.Response:
        sent["authorization"] = request.headers["authorization"]
        sent.update(json.loads(request.content))
        return httpx.Response(200, json=_completion(json.dumps({"post": "hello"})))

    respx.post(f"{LOCAL_BASE_URL}/chat/completions").mock(side_effect=_respond)

    result = await OpenAICompatibleLLM(LLMClient()).structured(
        model="llama3.3", messages=[{"role": "user", "content": "hi"}], response_model=_Answer
    )

    assert result.parsed == _Answer(post="hello")
    assert sent["authorization"] == "Bearer local-key"
    assert sent["model"] == "llama3.3"


@respx.mock
async def test_cache_hints_are_left_out_for_an_endpoint_other_than_openrouter(monkeypatch):
    monkeypatch.setattr(settings, "LLM_BASE_URL", LOCAL_BASE_URL)
    sent: dict[str, Any] = {}

    def _respond(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(200, json=_completion(json.dumps({"post": "hello"})))

    respx.post(f"{LOCAL_BASE_URL}/chat/completions").mock(side_effect=_respond)
    block = {
        "type": "text",
        "text": "be brief",
        "cache_control": {"type": "ephemeral", "ttl": "1h"},
    }
    messages = [{"role": "system", "content": [block]}, {"role": "user", "content": "hi"}]

    await OpenAICompatibleLLM(LLMClient()).structured(
        model="m", messages=messages, response_model=_Answer
    )

    assert sent["messages"] == [
        {"role": "system", "content": [{"type": "text", "text": "be brief"}]},
        {"role": "user", "content": "hi"},
    ]


@respx.mock
async def test_an_answer_without_usage_comes_back_parsed_with_no_usage():
    completion = _completion(json.dumps({"post": "hello"}))
    del completion["usage"]
    respx.post(COMPLETIONS_URL).mock(return_value=httpx.Response(200, json=completion))

    result = await OpenAICompatibleLLM(LLMClient()).structured(
        model="m", messages=[{"role": "user", "content": "x"}], response_model=_Answer
    )

    assert result.parsed == _Answer(post="hello")
    assert result.usage is None


def test_it_is_configured_only_with_the_key(monkeypatch):
    monkeypatch.setattr(settings, "LLM_API_KEY", "local-key")
    assert OpenAICompatibleLLM(LLMClient()).is_configured() is True

    monkeypatch.setattr(settings, "LLM_API_KEY", None)

    assert OpenAICompatibleLLM(LLMClient()).is_configured() is False


@respx.mock
async def test_model_calls_in_flight_are_capped_across_the_instance(monkeypatch):
    monkeypatch.setattr(settings, "LLM_CALLS_IN_FLIGHT", 2)
    in_flight = 0
    most = 0

    async def _respond(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, most
        in_flight += 1
        most = max(most, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return httpx.Response(200, json=_completion(json.dumps({"post": "hello"})))

    respx.post(COMPLETIONS_URL).mock(side_effect=_respond)
    message = [{"role": "user", "content": "x"}]

    # Separate adapters share the cap, as every area's calls do.
    results = await asyncio.gather(
        *(
            OpenAICompatibleLLM(LLMClient()).structured(
                model="m", messages=message, response_model=_Answer
            )
            for _ in range(5)
        )
    )

    assert [result.parsed.post for result in results] == ["hello"] * 5
    assert most == 2


async def test_a_call_waiting_for_a_slot_is_not_timed_out_by_its_wait(monkeypatch):
    monkeypatch.setattr(settings, "LLM_CALLS_IN_FLIGHT", 1)
    message = [{"role": "user", "content": "x"}]
    holding = FakeLLM(standing={"_Answer": {"post": "first"}}, latency=0.2)
    waiting = FakeLLM(standing={"_Answer": {"post": "second"}})

    first = asyncio.create_task(
        holding.structured(model="m", messages=message, response_model=_Answer)
    )
    await asyncio.sleep(0)
    second = await waiting.structured(
        model="m", messages=message, response_model=_Answer, timeout_seconds=0.05
    )

    assert second.parsed.post == "second"
    assert (await first).parsed.post == "first"


async def test_a_call_slower_than_its_timeout_once_sent_is_an_llm_error():
    slow = FakeLLM(standing={"_Answer": {"post": "late"}}, latency=1)

    with pytest.raises(LLMError, match="took over"):
        await slow.structured(
            model="m",
            messages=[{"role": "user", "content": "x"}],
            response_model=_Answer,
            timeout_seconds=0.01,
        )


@respx.mock
async def test_a_provider_slower_than_the_calls_timeout_is_an_llm_error():
    async def _respond(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json=_completion(json.dumps({"post": "late"})))

    respx.post(COMPLETIONS_URL).mock(side_effect=_respond)

    with pytest.raises(LLMError, match="took over"):
        await OpenAICompatibleLLM(LLMClient()).structured(
            model="m",
            messages=[{"role": "user", "content": "x"}],
            response_model=_Answer,
            timeout_seconds=0.01,
        )
