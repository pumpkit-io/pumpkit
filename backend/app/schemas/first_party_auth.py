from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.config import settings
from app.schemas.common import MessageResponse


class UserLogin(BaseModel):
    """User data for login"""

    email: EmailStr
    password: str = Field(max_length=settings.PASSWORD_MAX_LENGTH)

    @field_validator("email", mode="after")
    def lowercase_email(cls, v: str) -> str:
        return v.lower()


class UserSignup(BaseModel):
    """User data to create a new user"""

    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str

    @field_validator("email", mode="after")
    def lowercase_email(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        return v


class SignupResponse(BaseModel):
    """Response after successful signup with email confirmation"""

    message: str
    email: EmailStr

    @field_validator("email", mode="after")
    def lowercase_email(cls, v: str) -> str:
        return v.lower()


class PasswordResetRequest(BaseModel):
    """Request payload to initiate a password reset"""

    email: EmailStr

    @field_validator("email", mode="after")
    def lowercase_email(cls, v: str) -> str:
        return v.lower()


class PasswordResetConfirm(BaseModel):
    """Request payload to complete a password reset"""

    token: str
    new_password: str = Field(max_length=settings.PASSWORD_MAX_LENGTH)

    @field_validator("new_password")
    def validate_new_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        return v


class PasswordResetCompleteResponse(MessageResponse):
    """Response payload when a password reset is successful"""

    email: EmailStr

    @field_validator("email", mode="after")
    def lowercase_email(cls, v: str) -> str:
        return v.lower()


class ResendConfirmationEmailRequest(BaseModel):
    """Request payload to resend a confirmation email"""

    email: EmailStr

    @field_validator("email", mode="after")
    def lowercase_email(cls, v: str) -> str:
        return v.lower()
