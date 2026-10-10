from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.writing.constants import BRIEF_MAX_CHARS, FEEDBACK_MAX_CHARS


class PostStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brief: str = Field(..., max_length=BRIEF_MAX_CHARS)

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


class VersionResponse(BaseModel):
    id: str
    number: int
    # None for the first Version, which comes from the Brief.
    feedback: Optional[str]
    draft: str
    final: str
    # Counted by the backend the way the limit counts, which a browser's string length doesn't.
    final_char_count: int
    final_char_limit: int
    # What the slop check found in the Final, for the User to judge.
    tells: list[TellResponse]


class PostResponse(BaseModel):
    id: str
    brief: str
    versions: list[VersionResponse]
