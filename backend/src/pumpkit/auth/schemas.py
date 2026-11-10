from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from pumpkit.core.photos import MAX_PHOTO_DATA_URL_LENGTH, PHOTO_DATA_URL_PATTERN


class UserProfileResponse(BaseModel):
    """The current User's basic profile, built from the User with `model_validate`."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    first_name: Optional[str]
    last_name: Optional[str]
    avatar_data_url: Optional[str] = None
    x_handle: Optional[str] = None

    @field_validator("email", mode="after")
    def lowercase_email(cls, v: str) -> str:
        return v.lower()


class UserProfileUpdate(BaseModel):
    """Only supplied fields change; photo edits remain for legacy accounts until X-only cutover."""

    model_config = ConfigDict(extra="forbid")

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
        if len(v) > MAX_PHOTO_DATA_URL_LENGTH:
            raise ValueError("avatar payload too large")
        if not PHOTO_DATA_URL_PATTERN.fullmatch(v):
            raise ValueError(
                "must be a base64-encoded data URL of type image/jpeg, image/png or image/webp"
            )
        return v


class MagicLinkRequest(BaseModel):
    """Request payload to initiate a magic-link sign-in."""

    email: EmailStr

    @field_validator("email", mode="after")
    def lowercase_email(cls, v: str) -> str:
        return v.lower()
