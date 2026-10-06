import json
from typing import Any, Optional

import httpx
import pytest
import respx
from openai import APIStatusError
from pydantic import BaseModel

from app.core.config import settings
from app.core.openrouter import LLMNotConfiguredError, OpenRouterClient, openrouter_client
from app.schemas.openrouter import ModelUsage, StreamDelta

BASE_URL = "https://openrouter.ai/api/v1"


def _make_client() -> OpenRouterClient:
    """respx patches httpx globally, so the client needs no injected transport."""
    return OpenRouterClient()


def test_singleton_exported():
    assert isinstance(openrouter_client, OpenRouterClient)


def test_client_construction_does_not_touch_network():
    client = _make_client()
    assert client is not None


def _chat_completion_response(content: str) -> dict[str, Any]:
    """Minimal OpenAI-compatible chat completion response payload."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "openai/gpt-5",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
    }


@respx.mock
async def test_llm_complete_happy_path():
    captured: dict[str, Any] = {}

    def _responder(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_chat_completion_response("hello world"))

    respx.post(f"{BASE_URL}/chat/completions").mock(side_effect=_responder)

    client = _make_client()
    result = await client.llm_complete(
        model="openai/gpt-5",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert result.content == "hello world"
    assert result.model == "openai/gpt-5"
    # The mock response has no `usage` field, so usage is absent.
    assert result.usage is None
    assert captured["body"]["model"] == "openai/gpt-5"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]
    # None-valued params must be omitted.
    assert "temperature" not in captured["body"]
    assert "max_tokens" not in captured["body"]
    assert "top_p" not in captured["body"]


@respx.mock
async def test_llm_complete_passes_common_params():
    captured: dict[str, Any] = {}

    def _responder(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_chat_completion_response("ok"))

    respx.post(f"{BASE_URL}/chat/completions").mock(side_effect=_responder)

    client = _make_client()
    await client.llm_complete(
        model="openai/gpt-5",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.3,
        max_tokens=100,
        top_p=0.9,
    )

    assert captured["body"]["temperature"] == 0.3
    assert captured["body"]["max_tokens"] == 100
    assert captured["body"]["top_p"] == 0.9


@respx.mock
async def test_llm_complete_reasoning_effort_maps_to_unified_param():
    captured: dict[str, Any] = {}

    def _responder(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_chat_completion_response("ok"))

    respx.post(f"{BASE_URL}/chat/completions").mock(side_effect=_responder)

    client = _make_client()
    await client.llm_complete(
        model="openai/o3",
        messages=[{"role": "user", "content": "hi"}],
        reasoning_effort="high",
    )

    assert captured["body"]["reasoning"] == {"effort": "high"}


@respx.mock
async def test_llm_complete_extra_body_wins_on_conflict():
    captured: dict[str, Any] = {}

    def _responder(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json=_chat_completion_response("ok"))

    respx.post(f"{BASE_URL}/chat/completions").mock(side_effect=_responder)

    client = _make_client()
    await client.llm_complete(
        model="openai/o3",
        messages=[{"role": "user", "content": "hi"}],
        reasoning_effort="low",
        extra_body={"reasoning": {"effort": "high"}, "custom_flag": True},
    )

    assert captured["body"]["reasoning"] == {"effort": "high"}
    assert captured["body"]["custom_flag"] is True


@respx.mock
async def test_llm_complete_bubbles_api_error():
    respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": {"message": "boom"}})
    )

    client = _make_client()
    with pytest.raises(APIStatusError):
        await client.llm_complete(
            model="openai/gpt-5",
            messages=[{"role": "user", "content": "hi"}],
        )


def _sse_chunk(delta_content: Optional[str], *, final: bool = False) -> bytes:
    """Build one SSE data line matching OpenAI's streaming chunk shape."""
    if final:
        return b"data: [DONE]\n\n"
    payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "openai/gpt-5",
        "choices": [
            {
                "index": 0,
                "delta": {"content": delta_content} if delta_content is not None else {},
                "finish_reason": None,
            }
        ],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


def _sse_usage_chunk(
    *, prompt_tokens: int, completion_tokens: int, total_tokens: int, extras: Optional[dict] = None
) -> bytes:
    """Build the final pre-[DONE] chunk that carries usage when stream_options.include_usage is set."""
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        **(extras or {}),
    }
    payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "openai/gpt-5",
        "choices": [],
        "usage": usage,
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


@respx.mock
async def test_llm_stream_yields_stream_deltas_in_order():
    body = (
        _sse_chunk("Hel") + _sse_chunk("lo") + _sse_chunk(" world") + _sse_chunk(None, final=True)
    )
    respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        )
    )

    client = _make_client()
    events = []
    async for event in client.llm_stream(
        model="openai/gpt-5",
        messages=[{"role": "user", "content": "hi"}],
    ):
        events.append(event)

    assert all(isinstance(e, StreamDelta) for e in events)
    assert [e.text for e in events] == ["Hel", "lo", " world"]


@respx.mock
async def test_llm_stream_skips_empty_delta_chunks():
    body = (
        _sse_chunk(None)  # empty delta (e.g. role-only opener)
        + _sse_chunk("hi")
        + _sse_chunk(None, final=True)
    )
    respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        )
    )

    client = _make_client()
    events = [
        e
        async for e in client.llm_stream(
            model="openai/gpt-5",
            messages=[{"role": "user", "content": "hi"}],
        )
    ]
    assert [e.text for e in events if isinstance(e, StreamDelta)] == ["hi"]


@respx.mock
async def test_llm_stream_sends_stream_true_and_include_usage():
    captured: dict[str, Any] = {}

    def _responder(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse_chunk("x") + _sse_chunk(None, final=True),
        )

    respx.post(f"{BASE_URL}/chat/completions").mock(side_effect=_responder)

    client = _make_client()
    async for _ in client.llm_stream(
        model="openai/gpt-5",
        messages=[{"role": "user", "content": "hi"}],
    ):
        pass

    assert captured["body"]["stream"] is True
    assert captured["body"]["stream_options"] == {"include_usage": True}


@respx.mock
async def test_llm_stream_yields_usage_event_when_provider_includes_it():
    body = (
        _sse_chunk("a")
        + _sse_chunk("b")
        + _sse_usage_chunk(
            prompt_tokens=11,
            completion_tokens=2,
            total_tokens=13,
            extras={"prompt_tokens_details": {"cached_tokens": 4}},
        )
        + _sse_chunk(None, final=True)
    )
    respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        )
    )

    client = _make_client()
    events = [
        e
        async for e in client.llm_stream(
            model="openai/gpt-5",
            messages=[{"role": "user", "content": "hi"}],
        )
    ]

    deltas = [e for e in events if isinstance(e, StreamDelta)]
    usages = [e for e in events if isinstance(e, ModelUsage)]
    assert [d.text for d in deltas] == ["a", "b"]
    assert len(usages) == 1
    u = usages[0]
    assert (u.prompt_tokens, u.completion_tokens, u.total_tokens) == (11, 2, 13)
    assert u.raw["prompt_tokens_details"]["cached_tokens"] == 4


@respx.mock
async def test_llm_stream_handles_provider_without_usage():
    """A provider that ignores include_usage yields deltas and no ModelUsage event."""
    body = _sse_chunk("only") + _sse_chunk(None, final=True)
    respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        )
    )

    client = _make_client()
    events = [
        e
        async for e in client.llm_stream(
            model="openai/gpt-5",
            messages=[{"role": "user", "content": "hi"}],
        )
    ]
    assert [type(e) for e in events] == [StreamDelta]


class _Summary(BaseModel):
    title: str
    bullets: list[str]


@respx.mock
async def test_llm_structured_returns_parsed_pydantic_instance():
    payload_content = json.dumps({"title": "hi", "bullets": ["a", "b"]})

    def _responder(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "openai/gpt-5",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": payload_content},
                    }
                ],
            },
        )

    respx.post(f"{BASE_URL}/chat/completions").mock(side_effect=_responder)

    client = _make_client()
    result = await client.llm_structured(
        model="openai/gpt-5",
        messages=[{"role": "user", "content": "summarise"}],
        response_model=_Summary,
    )

    assert isinstance(result.parsed, _Summary)
    assert result.parsed.title == "hi"
    assert result.parsed.bullets == ["a", "b"]
    assert result.model == "openai/gpt-5"
    assert result.usage is None


@respx.mock
async def test_llm_structured_sends_json_schema_response_format():
    captured: dict[str, Any] = {}

    def _responder(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "openai/gpt-5",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"title": "t", "bullets": []}),
                        },
                    }
                ],
            },
        )

    respx.post(f"{BASE_URL}/chat/completions").mock(side_effect=_responder)

    client = _make_client()
    await client.llm_structured(
        model="openai/gpt-5",
        messages=[{"role": "user", "content": "x"}],
        response_model=_Summary,
    )

    rf = captured["body"]["response_format"]
    assert rf["type"] == "json_schema"
    assert "json_schema" in rf
    assert "title" in rf["json_schema"]["schema"]["properties"]
    assert "bullets" in rf["json_schema"]["schema"]["properties"]


async def test_unconfigured_client_raises_clear_error(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", None)
    client = OpenRouterClient()
    with pytest.raises(LLMNotConfiguredError, match="OPENROUTER_API_KEY"):
        await client.llm_complete(model="openai/gpt-5", messages=[{"role": "user", "content": "x"}])


def test_construction_without_key_does_not_raise(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", None)
    OpenRouterClient()
