"""The Resend adapter's Magic link message, built without calling Resend."""

from typing import Any, cast

from app.core.auth_mailer import MagicLinkEmail, read_logo_base64, resend_magic_link_params

EMAIL = MagicLinkEmail(
    to="alice@example.com",
    display_name="Alice",
    link_url="http://localhost:8000/api/v1/login/magic-link?token=abc",
    expires_in_minutes=15,
)


def _params() -> dict[str, Any]:
    # Read as a plain dict: Resend's TypedDicts mark every field optional.
    return cast(dict[str, Any], resend_magic_link_params(EMAIL, read_logo_base64()))


def test_magic_link_email_embeds_the_logo_inline_and_references_it_from_the_html():
    params = _params()

    [logo] = params["attachments"]
    assert logo["content_type"] == "image/png"
    assert logo["content"]
    assert f'src="cid:{logo["content_id"]}"' in params["html"]


def test_magic_link_email_carries_the_link_to_the_user():
    params = _params()

    assert params["to"] == ["alice@example.com"]
    assert params["subject"] == "Sign in to TestApp"
    assert "http://localhost:8000/api/v1/login/magic-link?token=abc" in params["html"]
    assert "TestApp" in params["html"]
