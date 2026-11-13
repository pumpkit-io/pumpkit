from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Per caller, for the route and the MCP tool that save a Positioning.
WRITE_RATE = "20/minute"

# A Positioning is a few sentences; this leaves room for a User who writes several paragraphs.
POSITIONING_MAX_CHARS = 4000


class PositioningSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., max_length=POSITIONING_MAX_CHARS)

    @field_validator("text")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Write your positioning first.")
        return stripped


class PositioningResponse(BaseModel):
    """The User's Positioning and when they last saved it; both null until they save one."""

    text: Optional[str]
    saved_at: Optional[datetime]
