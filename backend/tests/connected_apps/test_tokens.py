"""Two refreshes of one refresh token that race both get a pair, and the first rotation stands."""

from datetime import datetime, timedelta, timezone

from pumpkit.connected_apps.models import AppConnection, OAuthRefreshToken
from pumpkit.connected_apps.service import tokens
from pumpkit.core.time import as_utc
from tests.connected_apps.conftest import MCP_URL

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


async def test_a_second_rotation_of_a_stale_token_keeps_the_first(
    db, db_session_maker, user, oauth_client
):
    connection = AppConnection(
        user_id=user.id, client_id=oauth_client, scope="pumpkit", resource=MCP_URL, created_at=NOW
    )
    db.add(connection)
    await db.flush()
    original = await tokens.issue_pair(db, app_connection_id=connection.id, now=NOW)
    await db.commit()

    # Both sessions read the token before either rotates it, as two concurrent refreshes would.
    async with db_session_maker() as first, db_session_maker() as second:
        first_found = await tokens.find_refresh_token(first, original.refresh_token)
        second_found = await tokens.find_refresh_token(second, original.refresh_token)
        assert first_found is not None and second_found is not None
        # SQLite locks out a writer while another session's read is open.
        await second.commit()

        winner = await tokens.rotate(first, first_found[0], now=NOW)
        await first.commit()
        loser = await tokens.rotate(second, second_found[0], now=NOW + timedelta(minutes=1))
        await second.commit()

    assert loser.refresh_token != winner.refresh_token
    stored = await db.get(OAuthRefreshToken, original.refresh_token_id, populate_existing=True)
    assert stored is not None
    assert stored.replaced_by == winner.refresh_token_id
    assert stored.rotated_at is not None and as_utc(stored.rotated_at) == NOW
