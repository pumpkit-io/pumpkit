from typing import Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class XAuthorizationStartResponse(BaseModel):
    """X's consent screen, to send the browser to."""

    url: str


class XAuthorizationCompleteRequest(BaseModel):
    """What X's redirect handed the frontend callback route."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=2048)
    state: str = Field(..., min_length=1, max_length=512)


class XSignInStartQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_to: Optional[str] = Field(default=None, min_length=1, max_length=2048)

    @field_validator("return_to")
    @classmethod
    def internal_consent_destination(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        target = urlsplit(value)
        if (
            target.scheme
            or target.netloc
            or target.path != "/oauth/consent"
            or not target.query
            or target.fragment
            or "\\" in value
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise ValueError("Return to a pending consent request in this app.")
        return value


class XSignInCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str = Field(min_length=1, max_length=512)
    code: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    error: Optional[str] = Field(default=None, max_length=256)
