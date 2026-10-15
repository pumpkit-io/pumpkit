from typing import Optional

from pydantic import BaseModel


class MessageResponse(BaseModel):
    message: str


class LinkResponse(BaseModel):
    """What a browser-only MCP tool answers: what to do, and the web app page to do it on."""

    message: str
    # None when there is no page to open, such as billing on an Instance that sells no Plans.
    url: Optional[str]
