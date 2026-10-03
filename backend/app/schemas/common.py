from pydantic import BaseModel


class MessageResponse(BaseModel):
    """Generic response containing a message"""

    message: str
