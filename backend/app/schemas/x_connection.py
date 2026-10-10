from pydantic import BaseModel, ConfigDict, Field


class XConnectionResponse(BaseModel):
    """The User's X connection. Tokens never leave the backend."""

    handle: str
    # The longest Scheduled post X accepts from this account, in X's weighted characters.
    char_limit: int
    needs_reconnect: bool


class XAuthorizationStartResponse(BaseModel):
    """X's consent screen, to send the browser to."""

    url: str


class XAuthorizationCompleteRequest(BaseModel):
    """What X's redirect handed the frontend callback route."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=2048)
    state: str = Field(..., min_length=1, max_length=512)
