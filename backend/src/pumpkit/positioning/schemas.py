from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

# Per caller, for the route and the MCP tool that save a Positioning.
WRITE_RATE = "20/minute"

# A Positioning is a few sentences; this leaves room for a User who writes several paragraphs.
POSITIONING_MAX_CHARS = 4000


class PositioningSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str

    @field_validator("text")
    @classmethod
    def _strip(cls, value: str) -> str:
        # Postgres refuses a NUL in TEXT, and no one types one on purpose.
        stripped = value.replace("\x00", "").strip()
        if not stripped:
            raise ValueError("Write your positioning first.")
        if len(stripped) > POSITIONING_MAX_CHARS:
            raise ValueError(f"A positioning can be up to {POSITIONING_MAX_CHARS:,} characters.")
        return stripped


class PositioningResponse(BaseModel):
    """The User's Positioning and when they last saved it; both null until they save one."""

    text: Optional[str]
    saved_at: Optional[datetime]
