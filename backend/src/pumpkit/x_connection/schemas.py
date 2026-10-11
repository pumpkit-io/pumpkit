from pydantic import BaseModel, ConfigDict, Field


class XAuthorizationStartResponse(BaseModel):
    """X's consent screen, to send the browser to."""

    url: str


class XAuthorizationCompleteRequest(BaseModel):
    """What X's redirect handed the frontend callback route."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=2048)
    state: str = Field(..., min_length=1, max_length=512)
