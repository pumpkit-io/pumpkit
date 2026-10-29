"""
The `AuthMailer` port, so mediators never see the email provider.

`SmtpAuthMailer` sends through any SMTP server when SMTP is configured, `LogAuthMailer`
writes the Magic link to the log otherwise; tests override `get_auth_mailer` with `OutboxAuthMailer`.
"""

import asyncio
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr
from functools import lru_cache
from pathlib import Path
from typing import Optional, Protocol

from jinja2 import Environment, FileSystemLoader, select_autoescape

from pumpkit.core.config import SmtpSecurity, settings
from pumpkit.core.logging import logger

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_SMTP_TIMEOUT_SECONDS = 30


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


# PNG renders of frontend/src/assets/brand/*.svg, since mail clients don't show SVG.
# Re-render them whenever those SVGs change.
_ASSETS_DIR = _TEMPLATES_DIR / "emails" / "assets"
_BRAND_IMAGES = ("mascot", "wordmark-light", "wordmark-dark")
_WORDMARK_APP_NAME = "Pumpkit"


_email_templates = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),  # Escape user input against XSS
)


def _read_brand_images() -> dict[str, bytes]:
    return {name: (_ASSETS_DIR / f"{name}.png").read_bytes() for name in _BRAND_IMAGES}


def _magic_link_message(
    email: MagicLinkEmail, from_address: str, images: dict[str, bytes]
) -> EmailMessage:
    show_wordmark = settings.APP_NAME == _WORDMARK_APP_NAME
    html = _email_templates.get_template("emails/magic_link.html").render(
        display_name=email.display_name,
        magic_url=email.link_url,
        expires_in_minutes=email.expires_in_minutes,
        app_name=settings.APP_NAME,
        show_wordmark=show_wordmark,
    )
    message = EmailMessage()
    message["From"] = formataddr((settings.APP_NAME, from_address))
    message["To"] = email.to
    message["Subject"] = f"Sign in to {settings.APP_NAME}"
    message.set_content(
        f"Sign in to {settings.APP_NAME}: {email.link_url}\n"
        f"The link expires in {email.expires_in_minutes} minutes."
    )
    message.add_alternative(html, subtype="html")
    # With a filename the disposition defaults to attachment, which Gmail lists and won't render.
    html_part = message.get_body(preferencelist=("html",))
    assert html_part is not None
    for name, image in images.items():
        if name.startswith("wordmark") and not show_wordmark:
            continue
        html_part.add_related(
            image,
            maintype="image",
            subtype="png",
            cid=f"<{name}>",
            filename=f"{name}.png",
            disposition="inline",
        )
    return message


class SmtpAuthMailer:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        security: SmtpSecurity,
        username: Optional[str],
        password: Optional[str],
        from_address: str,
    ) -> None:
        self._host = host
        self._port = port
        self._security = security
        self._username = username
        self._password = password
        self._from_address = from_address
        self._images = _read_brand_images()

    async def send_magic_link(self, email: MagicLinkEmail) -> None:
        message = _magic_link_message(email, self._from_address, self._images)
        try:
            # smtplib blocks, so the send runs off the event loop.
            await asyncio.to_thread(self._send, message)
        except (smtplib.SMTPException, OSError) as error:
            raise AuthMailerError("The SMTP server could not send the Magic link email") from error

    def _send(self, message: EmailMessage) -> None:
        context = ssl.create_default_context()
        if self._security == "tls":
            client = smtplib.SMTP_SSL(
                self._host, self._port, timeout=_SMTP_TIMEOUT_SECONDS, context=context
            )
        else:
            client = smtplib.SMTP(self._host, self._port, timeout=_SMTP_TIMEOUT_SECONDS)
        with client:
            if self._security == "starttls":
                client.starttls(context=context)
            if self._username and self._password:
                client.login(self._username, self._password)
            client.send_message(message)


class LogAuthMailer:
    """Writes the Magic link to the log, for an Instance without SMTP."""

    async def send_magic_link(self, email: MagicLinkEmail) -> None:
        logger.warning(
            "Magic link for %s (expires in %d minutes): %s",
            email.to,
            email.expires_in_minutes,
            email.link_url,
        )


def announce_magic_link_delivery() -> None:
    """Say once at startup where Magic links go, so a Self-hoster without SMTP finds them."""
    if not settings.is_smtp_configured():
        logger.warning("SMTP is not configured: Magic links are written to this log")


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
    if settings.is_smtp_configured():
        return SmtpAuthMailer(
            host=settings.SMTP_HOST or "",
            port=settings.smtp_port(),
            security=settings.SMTP_SECURITY,
            username=settings.SMTP_USERNAME,
            password=settings.SMTP_PASSWORD,
            from_address=settings.EMAIL_FROM or "",
        )
    return LogAuthMailer()
