"""Authorize's opportunistic purge, and the transaction around it."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.connected_apps import mediator
from pumpkit.connected_apps.models import OAuthClient
from pumpkit.connected_apps.service.client_metadata import (
    FakeClientMetadataFetcher,
    FetchedClientMetadata,
)
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
        FakeClientMetadataFetcher(),
        now=NOW,
    )

    assert location == f"{CONSENT}?error=invalid_client"


DOCUMENT_URL = "https://app.example.com/oauth/client.json"


@dataclass
class observing_fetcher(FakeClientMetadataFetcher):
    """Records, while fetching, whether the request's session holds a transaction open."""

    db: Optional[AsyncSession] = None
    in_transaction: Optional[bool] = None
    stale_app_left: Optional[bool] = None

    async def fetch(self, url: str) -> FetchedClientMetadata:
        assert self.db is not None
        self.in_transaction = self.db.in_transaction()
        async with AsyncSession(self.db.bind) as other:
            self.stale_app_left = await other.get(OAuthClient, "oauth_client_stale") is not None
        return await super().fetch(url)


async def test_the_document_is_fetched_after_the_purge_is_committed_and_with_no_transaction_open(
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
    fetcher = observing_fetcher(db=foreign_keys_session)
    document: dict[str, Any] = {"client_id": DOCUMENT_URL, "redirect_uris": [REDIRECT]}
    fetcher.serve(document)

    location = await mediator.start_authorization(
        [
            ("client_id", DOCUMENT_URL),
            ("response_type", "code"),
            ("code_challenge", CHALLENGE),
            ("code_challenge_method", "S256"),
        ],
        foreign_keys_session,
        fetcher,
        now=NOW,
    )

    assert location.startswith(f"{CONSENT}?request=")
    assert fetcher.in_transaction is False
    assert fetcher.stale_app_left is False
