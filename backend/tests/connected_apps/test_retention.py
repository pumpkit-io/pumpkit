"""What `purge_expired` deletes, and what it keeps."""

from datetime import datetime, timedelta, timezone

import pytest

from pumpkit.auth.models import User
from pumpkit.connected_apps.models import (
    AppConnection,
    OAuthAccessToken,
    OAuthAuthorization,
    OAuthClient,
    OAuthRefreshToken,
)
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


async def user_with_connection(db, *, revoked_ago: timedelta | None = None) -> AppConnection:
    user = User(email="ana@example.com", display_name="Ana")
    db.add_all([user, metadata_document_client(expired_ago=timedelta(days=1))])
    await db.flush()
    connection = AppConnection(
        user_id=user.id,
        client_id=URL,
        scope="mcp",
        resource="https://example.com/mcp",
        created_at=NOW - timedelta(days=200),
        revoked_at=NOW - revoked_ago if revoked_ago else None,
    )
    db.add(connection)
    await db.flush()
    return connection


async def purge(db) -> None:
    await retention.purge_expired(db, now=NOW)
    await db.commit()
    db.expunge_all()


@pytest.mark.parametrize(
    ("expired_ago", "kept"), [(timedelta(hours=23), True), (timedelta(hours=25), False)]
)
async def test_an_access_token_is_purged_a_day_after_it_expires(
    foreign_keys_session, expired_ago, kept
):
    connection = await user_with_connection(foreign_keys_session)
    foreign_keys_session.add(
        OAuthAccessToken(
            id="access",
            app_connection_id=connection.id,
            token_hash="hash",
            created_at=NOW - expired_ago - timedelta(hours=1),
            expires_at=NOW - expired_ago,
        )
    )
    await foreign_keys_session.commit()

    await purge(foreign_keys_session)

    assert (await foreign_keys_session.get(OAuthAccessToken, "access") is not None) is kept


@pytest.mark.parametrize(
    ("expired_ago", "kept"), [(timedelta(days=89), True), (timedelta(days=91), False)]
)
async def test_a_refresh_token_is_purged_ninety_days_after_it_expires(
    foreign_keys_session, expired_ago, kept
):
    connection = await user_with_connection(foreign_keys_session)
    foreign_keys_session.add(
        OAuthRefreshToken(
            id="refresh",
            app_connection_id=connection.id,
            token_hash="hash",
            created_at=NOW - expired_ago - timedelta(days=90),
            expires_at=NOW - expired_ago,
        )
    )
    await foreign_keys_session.commit()

    await purge(foreign_keys_session)

    assert (await foreign_keys_session.get(OAuthRefreshToken, "refresh") is not None) is kept


@pytest.mark.parametrize(
    ("revoked_ago", "kept"),
    [(None, True), (timedelta(days=89), True), (timedelta(days=91), False)],
)
async def test_a_connection_is_purged_ninety_days_after_it_is_revoked(
    foreign_keys_session, revoked_ago, kept
):
    connection = await user_with_connection(foreign_keys_session, revoked_ago=revoked_ago)
    connection_id = connection.id
    foreign_keys_session.add(
        OAuthRefreshToken(
            id="refresh",
            app_connection_id=connection_id,
            token_hash="hash",
            created_at=NOW - timedelta(days=10),
            expires_at=NOW + timedelta(days=80),
        )
    )
    await foreign_keys_session.commit()

    await purge(foreign_keys_session)

    assert (await foreign_keys_session.get(AppConnection, connection_id) is not None) is kept
    assert (await foreign_keys_session.get(OAuthRefreshToken, "refresh") is not None) is kept
