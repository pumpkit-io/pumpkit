"""
The `AuthMailer` port, so mediators never see the email provider.

Production uses `ResendAuthMailer`; tests override `get_auth_mailer` with `OutboxAuthMailer`.
"""

import base64
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import resend
from resend.exceptions import ResendError

from app.core.config import settings
from app.core.templates import templates_helper


class AuthMailerError(Exception):
    """The auth email could not be sent."""


@dataclass(frozen=True)
class MagicLinkEmail:
    to: str
    display_name: str
    link_url: str
    expires_in_minutes: int


class AuthMailer(Protocol):
    async def send_magic_link(self, email: MagicLinkEmail) -> None:
        """Send the Magic link email, or raise `AuthMailerError`."""
        ...


# Logo embedded inline in the Magic link email via CID. Replace
# templates/emails/assets/logo.png with your own logo.
_LOGO_PATH = Path(__file__).resolve().parent.parent / "templates" / "emails" / "assets" / "logo.png"
_LOGO_CONTENT_ID = "app-logo"


def resend_magic_link_params(email: MagicLinkEmail, logo_base64: str) -> resend.Emails.SendParams:
    html = templates_helper.render_template(
        "emails/magic_link.html",
        display_name=email.display_name,
        magic_url=email.link_url,
        expires_in_minutes=email.expires_in_minutes,
        app_name=settings.APP_NAME,
        logo_cid=_LOGO_CONTENT_ID,
    )
    return {
        "from": f"{settings.APP_NAME} <{settings.RESEND_NOREPLY_ADDRESS}>",
        "to": [email.to],
        "subject": f"Sign in to {settings.APP_NAME}",
        "html": html,
        "attachments": [
            {
                "filename": "logo.png",
                "content": logo_base64,
                "content_type": "image/png",
                "content_id": _LOGO_CONTENT_ID,
            }
        ],
    }


def read_logo_base64() -> str:
    return base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")


class ResendAuthMailer:
    def __init__(self) -> None:
        resend.api_key = settings.RESEND_API_KEY
        self._logo_base64 = read_logo_base64()

    async def send_magic_link(self, email: MagicLinkEmail) -> None:
        try:
            await resend.Emails.send_async(resend_magic_link_params(email, self._logo_base64))
        except ResendError as error:
            raise AuthMailerError("Resend could not send the Magic link email") from error


@dataclass
class OutboxAuthMailer:
    """In-memory outbox for tests; `fail = True` makes sends raise `AuthMailerError`."""

    messages: list[MagicLinkEmail] = field(default_factory=list)
    fail: bool = False

    async def send_magic_link(self, email: MagicLinkEmail) -> None:
        if self.fail:
            raise AuthMailerError("Outbox is set to fail")
        self.messages.append(email)


@lru_cache
def get_auth_mailer() -> AuthMailer:
    """FastAPI dependency for the `AuthMailer` port."""
    return ResendAuthMailer()
