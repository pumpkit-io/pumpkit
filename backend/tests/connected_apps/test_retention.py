"""What `purge_expired` deletes, and what it keeps."""

from datetime import datetime, timedelta, timezone

import pytest

from pumpkit.auth.models import User
from pumpkit.connected_apps.models import AppConnection, OAuthAuthorization, OAuthClient
from pumpkit.connected_apps.service import retention
from tests.oauth_app import CHALLENGE, REDIRECT

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
URL = "https://app.example.com/oauth/client.json"


def metadata_document_client(*, expired_ago: timedelta) -> OAuthClient:
    return OAuthClient(
        id=URL,
        kind="metadata_document",
        name="Example",
        redirect_uris=[REDIRECT],
        token_endpoint_auth_method="none",
        metadata_fetched_at=NOW - expired_ago - timedelta(days=1),
        metadata_expires_at=NOW - expired_ago,
        created_at=NOW - expired_ago - timedelta(days=1),
    )


async def survives_purge(db) -> bool:
    await retention.purge_expired(db, now=NOW)
    await db.commit()
    db.expunge_all()
    return await db.get(OAuthClient, URL) is not None


async def test_a_document_app_stale_for_thirty_days_and_unused_is_purged(foreign_keys_session):
    foreign_keys_session.add(metadata_document_client(expired_ago=timedelta(days=31)))
    await foreign_keys_session.commit()

    assert not await survives_purge(foreign_keys_session)


async def test_a_document_app_stale_for_less_than_thirty_days_is_kept(foreign_keys_session):
    foreign_keys_session.add(metadata_document_client(expired_ago=timedelta(days=29)))
    await foreign_keys_session.commit()

    assert await survives_purge(foreign_keys_session)


@pytest.mark.parametrize("revoked", [False, True])
async def test_a_document_app_with_a_connection_is_kept(foreign_keys_session, revoked):
    user = User(email="ana@example.com", display_name="Ana")
    foreign_keys_session.add_all([user, metadata_document_client(expired_ago=timedelta(days=60))])
    await foreign_keys_session.flush()
    foreign_keys_session.add(
        AppConnection(
            user_id=user.id,
            client_id=URL,
            scope="mcp",
            resource="https://example.com/mcp",
            created_at=NOW - timedelta(days=60),
            revoked_at=NOW - timedelta(days=40) if revoked else None,
        )
    )
    await foreign_keys_session.commit()

    assert await survives_purge(foreign_keys_session)


async def test_a_document_app_with_a_recent_authorization_is_kept(foreign_keys_session):
    foreign_keys_session.add(metadata_document_client(expired_ago=timedelta(days=60)))
    await foreign_keys_session.flush()
    foreign_keys_session.add(
        OAuthAuthorization(
            id="request",
            client_id=URL,
            redirect_uri=REDIRECT,
            redirect_uri_was_sent=True,
            code_challenge=CHALLENGE,
            scope="mcp",
            resource="https://example.com/mcp",
            created_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(minutes=9),
        )
    )
    await foreign_keys_session.commit()

    assert await survives_purge(foreign_keys_session)
