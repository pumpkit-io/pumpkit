from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from pumpkit.core.text import drop_unstorable

# Per caller, for the route and the MCP tool that save a Positioning.
WRITE_RATE = "20/minute"

# A Positioning is a few sentences; this leaves room for a User who writes several paragraphs.
POSITIONING_MAX_CHARS = 4000


class PositioningSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str

    # Before the field's checks, so a refusal never echoes text the response can't encode.
    @model_validator(mode="before")
    @classmethod
    def _drop_unstorable(cls, data: object) -> object:
        if isinstance(data, dict) and isinstance(data.get("text"), str):
            return {**data, "text": drop_unstorable(data["text"])}
        return data

    @field_validator("text")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Write your positioning first.")
        if len(stripped) > POSITIONING_MAX_CHARS:
            raise ValueError(f"A positioning can be up to {POSITIONING_MAX_CHARS:,} characters.")
        return stripped


class PositioningResponse(BaseModel):
    """The User's Positioning and when they last saved it; both null until they save one."""

    text: Optional[str]
    saved_at: Optional[datetime]


class PositioningPageResponse(PositioningResponse):
    """The User's Positioning as the web app's panel reads it."""

    # False once the User has used up today's drafts.
    can_draft: bool


class PositioningDraftResponse(BaseModel):
    """A draft of the User's Positioning, or `reason`: why none could be made, in words for them."""

    text: Optional[str]
    reason: Optional[str]
    can_draft: bool
