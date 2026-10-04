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
    to: str
    display_name: str
    link_url: str
    expires_in_minutes: int


class AuthMailer(Protocol):
    async def send_magic_link(
        self,
        *,
        to: str,
        display_name: str,
        link_url: str,
        expires_in_minutes: int,
    ) -> None:
        """Send the Magic link email, or raise `AuthMailerError`."""
        ...


# Logo embedded inline in the Magic link email via CID. Replace
# templates/emails/assets/logo.png with your own logo.
_LOGO_PATH = Path(__file__).resolve().parent.parent / "templates" / "emails" / "assets" / "logo.png"
_LOGO_CONTENT_ID = "app-logo"


class ResendAuthMailer:
    """Sends auth email through Resend, rendering the template with the inline logo."""

    def __init__(self) -> None:
        resend.api_key = settings.RESEND_API_KEY
        self._logo_base64 = base64.b64encode(_LOGO_PATH.read_bytes()).decode("ascii")

    async def send_magic_link(
        self,
        *,
        to: str,
        display_name: str,
        link_url: str,
        expires_in_minutes: int,
    ) -> None:
        html = templates_helper.render_template(
            "emails/magic_link.html",
            display_name=display_name,
            magic_url=link_url,
            expires_in_minutes=expires_in_minutes,
            app_name=settings.APP_NAME,
            logo_cid=_LOGO_CONTENT_ID,
        )
        try:
            await resend.Emails.send_async(
                {
                    "from": f"{settings.APP_NAME} <{settings.RESEND_NOREPLY_ADDRESS}>",
                    "to": [to],
                    "subject": f"Sign in to {settings.APP_NAME}",
                    "html": html,
                    "attachments": [
                        {
                            "filename": "logo.png",
                            "content": self._logo_base64,
                            "content_type": "image/png",
                            "content_id": _LOGO_CONTENT_ID,
                        }
                    ],
                }
            )
        except ResendError as error:
            raise AuthMailerError("Resend could not send the Magic link email") from error


@dataclass
class OutboxAuthMailer:
    """Records sent auth email in memory. Set `fail = True` to make sends raise `AuthMailerError`."""

    messages: list[MagicLinkEmail] = field(default_factory=list)
    fail: bool = False

    async def send_magic_link(
        self,
        *,
        to: str,
        display_name: str,
        link_url: str,
        expires_in_minutes: int,
    ) -> None:
        if self.fail:
            raise AuthMailerError("Outbox is set to fail")
        self.messages.append(
            MagicLinkEmail(
                to=to,
                display_name=display_name,
                link_url=link_url,
                expires_in_minutes=expires_in_minutes,
            )
        )


@lru_cache
def get_auth_mailer() -> AuthMailer:
    """FastAPI dependency for the `AuthMailer` port."""
    return ResendAuthMailer()
