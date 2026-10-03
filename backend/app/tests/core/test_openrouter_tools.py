import pytest

from app.core.openrouter import openrouter_client
from app.schemas.openrouter import AssembledToolCall


class _Delta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _TCFrag:
    def __init__(self, index, id=None, name=None, arguments=""):
        self.index = index
        self.id = id
        self.function = type("F", (), {"name": name, "arguments": arguments})()


class _Choice:
    def __init__(self, delta):
        self.delta = delta


class _Chunk:
    def __init__(self, delta):
        self.choices = [_Choice(delta)]
        self.usage = None


async def _fake_stream(chunks):
    for c in chunks:
        yield c


@pytest.mark.asyncio
async def test_stream_reassembles_tool_call(monkeypatch):
    chunks = [
        _Chunk(_Delta(tool_calls=[_TCFrag(0, id="call_1", name="lookup", arguments='{"que')])),
        _Chunk(_Delta(tool_calls=[_TCFrag(0, arguments='ry":"hi"}')])),
    ]

    async def fake_create(**kwargs):
        assert kwargs["tools"][0]["function"]["name"] == "lookup"
        return _fake_stream(chunks)

    monkeypatch.setattr(
        openrouter_client._llm_client.chat.completions, "create", fake_create
    )

    events = []
    async for ev in openrouter_client.llm_stream(
        model="m", messages=[], tools=[{"type": "function",
                                        "function": {"name": "lookup"}}]
    ):
        events.append(ev)

    assembled = [e for e in events if isinstance(e, AssembledToolCall)]
    assert len(assembled) == 1
    assert assembled[0].id == "call_1"
    assert assembled[0].name == "lookup"
    assert assembled[0].arguments == '{"query":"hi"}'
