from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


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
    """Only supplied name fields change; X supplies the photo and contact identity."""

    model_config = ConfigDict(extra="forbid")

    first_name: Optional[str] = None
    last_name: Optional[str] = None

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


class MagicLinkRequest(BaseModel):
    """Request payload to initiate a magic-link sign-in."""

    email: EmailStr

    @field_validator("email", mode="after")
    def lowercase_email(cls, v: str) -> str:
        return v.lower()
