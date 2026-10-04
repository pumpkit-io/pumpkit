"""
The `AuthMailer` port: the email a User receives to sign in.

Mediators depend on the port through `get_auth_mailer`; they never see the
email provider. `ResendAuthMailer` is the production adapter and
`OutboxAuthMailer` records messages in memory (tests override the dependency
with it).
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
    """The Magic link email a User receives: who it goes to and the link it carries."""

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
    """
    The Resend send parameters for a Magic link email: the rendered template,
    with the logo attached inline and referenced from the HTML by its content ID.
    """
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
    """The email logo, base64-encoded for an inline attachment."""
    return base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")


class ResendAuthMailer:
    """Sends auth email through Resend, rendering the template with the inline logo."""

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
    """Records sent auth email in memory. Set `fail = True` to make sends raise `AuthMailerError`."""

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
