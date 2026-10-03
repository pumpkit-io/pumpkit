from unittest.mock import MagicMock

from starlette.requests import Request

import app.api.mediators.magic_link_auth as magic_link_mediator


def _request() -> Request:
    return Request(
        {"type": "http", "method": "POST", "path": "/", "headers": [], "client": ("1.2.3.4", 1)}
    )


async def test_magic_link_email_embeds_logo_by_cid(db, monkeypatch):
    sent = MagicMock()
    monkeypatch.setattr(magic_link_mediator.resend.Emails, "send", sent)

    await magic_link_mediator.request_magic_link(email="new@example.com", request=_request(), db=db)

    payload = sent.call_args.args[0]
    attachment = payload["attachments"][0]
    assert attachment["content_id"] == "app-logo"
    assert attachment["content_type"] == "image/png"
    assert attachment["content"]  # base64 body
    assert 'src="cid:app-logo"' in payload["html"]
    assert "via.placeholder.com" not in payload["html"]
    assert "TestApp" in payload["html"]
