from dataclasses import dataclass, field
from typing import Any, Generic, Optional, TypeVar, Union

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class ModelUsage:
    """Token usage reported by an OpenRouter model call, streamed or not.

    Streamed calls get it from the final chunk, sent only with `include_usage` set.
    `raw` keeps the full provider payload (e.g. `cost`, `prompt_tokens_details`).
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StreamDelta:
    """One content delta from a streaming chat completion."""

    text: str


@dataclass(frozen=True)
class ToolCallDelta:
    """A fragment of a streamed tool call, keyed by its position index."""

    index: int
    id: Optional[str]
    name: Optional[str]
    arguments: str  # partial JSON fragment


@dataclass(frozen=True)
class AssembledToolCall:
    """A fully reassembled tool call, emitted once the stream round ends."""

    id: str
    name: str
    arguments: str  # complete JSON string


StreamEvent = Union[StreamDelta, ModelUsage, ToolCallDelta, AssembledToolCall]


@dataclass(frozen=True)
class CompleteResult:
    """Result of a non-streamed, non-structured chat completion call."""

    content: str
    model: str
    usage: Optional[ModelUsage]


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    """Result of a non-streamed, structured chat completion call."""

    parsed: T
    model: str
    usage: Optional[ModelUsage]
