from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from pumpkit.posts.formats import FORMAT_POST, Format
from pumpkit.posts.writing.constants import BRIEF_MAX_CHARS, FEEDBACK_MAX_CHARS

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


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback: str = Field(..., max_length=FEEDBACK_MAX_CHARS)
    # None keeps the latest Version's Format.
    format: Optional[Format] = None

    @field_validator("feedback")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Write some Feedback first.")
        return stripped


class TellResponse(BaseModel):
    name: str
    description: str


class PartResponse(BaseModel):
    """One Part of a Version's text."""

    text: str
    # Counted by the backend the way the limit counts, which a browser's string length doesn't.
    char_count: int
    char_limit: int


class VersionResponse(BaseModel):
    id: str
    number: int
    # None for the first Version, which comes from the Brief.
    feedback: Optional[str]
    format: Format
    # The Version's text, one Part at a time, in order.
    parts: list[PartResponse]
    # What the slop check found in any Part of the text, for the User to judge.
    tells: list[TellResponse]
    created_at: datetime


class TextResponse(BaseModel):
    """A Post's Text (ADR 0016)."""

    format: Format
    parts: list[PartResponse]
    # The Version it came from: the last one written or restored.
    version_number: int
    # Whether the User changed it since it came from that Version.
    edited: bool


class PostResponse(BaseModel):
    id: str
    brief: str
    versions: list[VersionResponse]


class VersionToolResponse(BaseModel):
    """A Version as the MCP tools answer with it, without the tells."""

    id: str
    number: int
    feedback: Optional[str]
    format: Format
    parts: list[PartResponse]
    created_at: datetime


class PostToolResponse(BaseModel):
    id: str
    brief: str
    versions: list[VersionToolResponse]
