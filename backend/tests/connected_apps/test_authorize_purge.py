"""Authorize's opportunistic purge never deletes the app the request is from."""

from datetime import datetime, timedelta, timezone

from pumpkit.connected_apps import mediator
from pumpkit.connected_apps.models import OAuthClient
from tests.oauth_app import CHALLENGE, CONSENT, REDIRECT

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


async def test_an_app_unused_for_thirty_days_is_purged_before_its_request_is_stored(
    foreign_keys_session,
):
    foreign_keys_session.add(
        OAuthClient(
            id="oauth_client_stale",
            kind="registered",
            name="Gemini CLI",
            redirect_uris=[REDIRECT],
            token_endpoint_auth_method="none",
            created_at=NOW - timedelta(days=31),
        )
    )
    await foreign_keys_session.commit()

    location = await mediator.start_authorization(
        [
            ("client_id", "oauth_client_stale"),
            ("response_type", "code"),
            ("code_challenge", CHALLENGE),
            ("code_challenge_method", "S256"),
        ],
        foreign_keys_session,
        now=NOW,
    )

    assert location == f"{CONSENT}?error=invalid_client"
