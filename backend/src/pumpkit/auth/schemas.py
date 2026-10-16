import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

# About 200 KB of base64: client-resized 256x256 JPEGs are 30-60 KB, so PNG/webp still fit.
_MAX_AVATAR_DATA_URL_LEN = 220_000
_AVATAR_DATA_URL_PATTERN = re.compile(r"data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+")


class UserProfileResponse(BaseModel):
    """The current User's basic profile."""

    id: str
    email: EmailStr
    first_name: Optional[str]
    last_name: Optional[str]
    avatar_data_url: Optional[str] = None

    @field_validator("email", mode="after")
    def lowercase_email(cls, v: str) -> str:
        return v.lower()


class UserProfileUpdate(BaseModel):
    """Partial update of the current User's editable profile fields.

    Only fields set in the request body are applied; ``null`` clears a field (e.g. the avatar).
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


class MagicLinkRequest(BaseModel):
    """Request payload to initiate a magic-link sign-in."""

    email: EmailStr

    @field_validator("email", mode="after")
    def lowercase_email(cls, v: str) -> str:
        return v.lower()


class ApiKeyCreateRequest(BaseModel):
    """The name a User gives a new API key, such as the machine or tool that will use it."""

    model_config = ConfigDict(extra="forbid")

    name: str

    @field_validator("name", mode="after")
    def trim_name(cls, v: str) -> str:
        trimmed = v.strip()
        if trimmed == "":
            raise ValueError("must not be empty")
        if len(trimmed) > 80:
            raise ValueError("must be 80 characters or fewer")
        return trimmed


class ApiKeyResponse(BaseModel):
    """An API key as its owner sees it: never the secret or its hash."""

    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: Optional[datetime]


class ApiKeyCreatedResponse(BaseModel):
    """A new API key with its secret and the command that adds it to Claude Code, shown once."""

    api_key: ApiKeyResponse
    secret: str
    claude_command: str


class ApiKeysListResponse(BaseModel):
    """The User's unrevoked API keys, oldest first."""

    data: list[ApiKeyResponse]
