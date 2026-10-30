from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pumpkit.posts.formats import FORMAT_POST, Format
from pumpkit.posts.writing.constants import BRIEF_MAX_CHARS

# Per caller, for the routes and MCP tools that write a Version.
WRITE_RATE = "20/minute"


class PostStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: str = Field(..., max_length=BRIEF_MAX_CHARS)
    format: Format = FORMAT_POST

    @field_validator("brief")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Write a Brief first.")
        return stripped


class PartResponse(BaseModel):
    """One Part of a Version's text."""

    text: str
    # Counted by the backend the way the limit counts, which a browser's string length doesn't.
    char_count: int
    char_limit: int


class StartingTextResponse(BaseModel):
    """The Post's Text a Feedback was given on, when it differed from the Version before."""

    format: Format
    parts: list[PartResponse]
    version_number: int


class VersionResponse(BaseModel):
    id: str
    number: int
    # None for the first Version, which comes from the Brief.
    feedback: Optional[str]
    format: Format
    # The Version's text, one Part at a time, in order.
    parts: list[PartResponse]
    starting_text: Optional[StartingTextResponse]
    created_at: datetime


class TextResponse(BaseModel):
    """A Post's Text (ADR 0016)."""

    format: Format
    parts: list[PartResponse]
    # The Version it came from: the last one written or restored.
    version_number: int
    edited: bool


class PostResponse(BaseModel):
    id: str
    brief: str
    versions: list[VersionResponse]
