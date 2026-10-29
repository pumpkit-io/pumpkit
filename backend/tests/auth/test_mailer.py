"""The `AuthMailer` adapters: SMTP against an in-process server, and the log fallback."""

import email
import logging
import socket
from email.message import EmailMessage
from email.policy import default as default_policy

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.handlers import Message

from pumpkit.auth.mailer import LogAuthMailer, MagicLinkEmail, SmtpAuthMailer
from pumpkit.core.config import settings
from pumpkit.main import app, lifespan

LINK = "http://localhost:8000/api/v1/login/magic-link?token=abc"
EMAIL = MagicLinkEmail(
    to="alice@example.com",
    display_name="Alice",
    link_url=LINK,
    expires_in_minutes=15,
)


class _Inbox(Message):
    def __init__(self) -> None:
        super().__init__()
        self.received: list[EmailMessage] = []

    def handle_message(self, message) -> None:
        self.received.append(email.message_from_bytes(message.as_bytes(), policy=default_policy))  # pyright: ignore[reportArgumentType]


@pytest.fixture
def smtp_inbox():
    # aiosmtpd's Controller cannot start on port 0, so borrow a free port from the OS.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    inbox = _Inbox()
    controller = Controller(inbox, hostname="127.0.0.1", port=port)
    controller.start()
    yield inbox, controller.port
    controller.stop()


def _smtp_mailer(port: int) -> SmtpAuthMailer:
    return SmtpAuthMailer(
        host="127.0.0.1",
        port=port,
        security="none",
        username=None,
        password=None,
        from_address="noreply@example.com",
    )


def _inline_images(message: EmailMessage, html: str) -> list[str]:
    """The content ids of the PNG parts, checking each is inline and referenced by the HTML."""
    content_ids = []
    for part in message.walk():
        if part.get_content_type() != "image/png":
            continue
        content_id = part["Content-ID"].strip("<>")
        assert part.get_content_disposition() == "inline"
        assert f'src="cid:{content_id}"' in html
        assert part.get_payload(decode=True)
        content_ids.append(content_id)
    return content_ids


async def test_smtp_mailer_sends_the_magic_link_email_with_the_mascot_inline(smtp_inbox):
    inbox, port = smtp_inbox

    await _smtp_mailer(port).send_magic_link(EMAIL)

    [message] = inbox.received
    assert message["To"] == "alice@example.com"
    assert message["From"] == "TestApp <noreply@example.com>"
    assert message["Subject"] == "Sign in to TestApp"
    html_part = message.get_body(preferencelist=("html",))
    assert html_part is not None
    html = html_part.get_content()
    assert LINK in html.replace("&amp;", "&")
    assert _inline_images(message, html) == ["mascot"]
    assert ">TestApp</span>" in html


async def test_smtp_mailer_shows_the_wordmark_while_the_app_is_pumpkit(smtp_inbox, monkeypatch):
    monkeypatch.setattr(settings, "APP_NAME", "Pumpkit")
    inbox, port = smtp_inbox

    await _smtp_mailer(port).send_magic_link(EMAIL)

    [message] = inbox.received
    html_part = message.get_body(preferencelist=("html",))
    assert html_part is not None
    html = html_part.get_content()
    assert _inline_images(message, html) == ["mascot", "wordmark-light", "wordmark-dark"]


async def test_log_mailer_writes_the_link_recipient_and_expiry_at_warning(caplog):
    with caplog.at_level(logging.WARNING):
        await LogAuthMailer().send_magic_link(EMAIL)

    [record] = [r for r in caplog.records if LINK in r.getMessage()]
    assert record.levelno == logging.WARNING
    assert "alice@example.com" in record.getMessage()
    assert "15 minutes" in record.getMessage()


async def test_startup_says_magic_links_go_to_the_log_without_smtp(caplog):
    with caplog.at_level(logging.INFO):
        async with lifespan(app):
            pass

    assert any("Magic links are written to this log" in r.getMessage() for r in caplog.records)
