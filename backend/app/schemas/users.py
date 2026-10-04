import re
from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator

# Cap base64 payload roughly to 200 KB of encoded text. Client-side resize
# targets 256x256 JPEG quality 0.85 → typically 30-60 KB encoded; this leaves
# headroom for PNG/webp inputs while bounding row size.
_MAX_AVATAR_DATA_URL_LEN = 220_000
_AVATAR_DATA_URL_PATTERN = re.compile(r"data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+")


class UserProfileResponse(BaseModel):
    """Response payload containing the current user's basic profile information."""

    id: str
    email: EmailStr
    first_name: Optional[str]
    last_name: Optional[str]
    avatar_data_url: Optional[str] = None

    @field_validator("email", mode="after")
    def lowercase_email(cls, v: str) -> str:
        return v.lower()


class UserProfileUpdate(BaseModel):
    """Partial update for the current user's editable profile fields.

    All fields are optional; only fields explicitly set in the request body
    (``model_dump(exclude_unset=True)``) are applied. Pass ``null`` to clear
    a field (e.g. avatar removal).
    """

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    avatar_data_url: Optional[str] = None

    @field_validator("first_name", "last_name", mode="after")
    def trim_or_null(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        trimmed = v.strip()
        if trimmed == "":
            return None
        if len(trimmed) > 80:
            raise ValueError("must be 80 characters or fewer")
        return trimmed

    @field_validator("avatar_data_url", mode="after")
    def validate_avatar(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if len(v) > _MAX_AVATAR_DATA_URL_LEN:
            raise ValueError("avatar payload too large")
        if not _AVATAR_DATA_URL_PATTERN.fullmatch(v):
            raise ValueError(
                "must be a base64-encoded data URL of type image/jpeg, image/png or image/webp"
            )
        return v
