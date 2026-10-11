from pydantic import BaseModel, EmailStr, field_validator


class MagicLinkRequest(BaseModel):
    """Request payload to initiate a magic-link sign-in."""

    email: EmailStr

    @field_validator("email", mode="after")
    def lowercase_email(cls, v: str) -> str:
        return v.lower()
