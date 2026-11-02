"""A User's Connected apps: listing and disconnecting them, one unrevoked connection per app."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import ORMExecuteState

from pumpkit.connected_apps.models import AppConnection, OAuthClient
from pumpkit.connected_apps.service import connections
from tests.connected_apps.conftest import (
    MCP_URL,
    REDIRECT,
    approved_code,
    exchange,
    refresh,
    register,
)
from tests.mcp_client import McpClient

CONNECTIONS = "/api/v1/app-connections"


@pytest.fixture
def app(new_browser):
    return new_browser()


async def connect(authed_client, app, client_id: str) -> dict[str, str]:
    """The app's tokens once `authed_client`'s User has connected it."""
    code = await approved_code(authed_client, app, client_id)
    return (await exchange(app, client_id, code)).json()


async def listed(browser) -> list[dict]:
    response = await browser.get(CONNECTIONS)
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def test_the_list_shows_each_connected_app_newest_first(
    subscribed, clock, authed_client, app, oauth_client, db
):
    db.add(
        OAuthClient(
            id="https://claude.ai/oauth/mcp-oauth-client-metadata",
            kind="metadata_document",
            name="Claude",
            redirect_uris=[REDIRECT],
            token_endpoint_auth_method="none",
            created_at=clock(),
        )
    )
    await db.commit()
    first_connected = clock()
    await connect(authed_client, app, oauth_client)
    clock.advance(timedelta(days=1))
    await connect(authed_client, app, "https://claude.ai/oauth/mcp-oauth-client-metadata")

    apps = await listed(authed_client)

    assert [(a["app_name"], a["verified_domain"]) for a in apps] == [
        ("Claude", "claude.ai"),
        ("Gemini CLI", None),
    ]
    assert datetime.fromisoformat(apps[1]["created_at"]) == first_connected
    assert apps[1]["last_used_at"] is None


async def test_the_list_shows_when_an_app_last_used_pumpkit(
    subscribed, clock, authed_client, app, oauth_client
):
    tokens = await connect(authed_client, app, oauth_client)
    clock.advance(timedelta(minutes=30))
    used_at = clock()

    await McpClient(app, tokens["access_token"]).send("tools/list")

    [connected] = await listed(authed_client)
    assert datetime.fromisoformat(connected["last_used_at"]) == used_at


async def test_connecting_the_same_app_twice_shows_one_row(
    subscribed, clock, authed_client, app, oauth_client
):
    await connect(authed_client, app, oauth_client)
    await connect(authed_client, app, oauth_client)

    assert len(await listed(authed_client)) == 1


async def test_the_list_leaves_out_other_users_and_disconnected_apps(
    subscribed,
    clock,
    authed_client,
    app,
    oauth_client,
    new_browser,
    sign_in_by_magic_link,
    sells_no_plans,
):
    other_app = await register(app, REDIRECT, client_name="Cursor")
    await connect(authed_client, app, oauth_client)
    [kept] = await listed(authed_client)
    await authed_client.delete(f"{CONNECTIONS}/{kept['id']}")
    bob = new_browser()
    signed_in = await sign_in_by_magic_link(bob, "bob@example.com")
    bob.headers["Authorization"] = f"Bearer {signed_in.access_token}"
    await connect(bob, app, other_app)

    assert await listed(authed_client) == []
    assert [a["app_name"] for a in await listed(bob)] == ["Cursor"]


async def test_disconnecting_kills_the_apps_access_and_refresh_tokens(
    subscribed, clock, authed_client, app, oauth_client
):
    tokens = await connect(authed_client, app, oauth_client)
    [connected] = await listed(authed_client)

    response = await authed_client.delete(f"{CONNECTIONS}/{connected['id']}")

    assert response.status_code == 204, response.text
    assert await listed(authed_client) == []
    assert (await McpClient(app, tokens["access_token"]).send("tools/list")).status_code == 401
    refused = await refresh(app, oauth_client, tokens["refresh_token"])
    assert refused.json()["error"] == "invalid_grant"


async def test_disconnecting_another_users_app_is_404_and_leaves_it_connected(
    subscribed,
    clock,
    authed_client,
    app,
    oauth_client,
    new_browser,
    sign_in_by_magic_link,
):
    tokens = await connect(authed_client, app, oauth_client)
    [connected] = await listed(authed_client)
    bob = new_browser()
    signed_in = await sign_in_by_magic_link(bob, "bob@example.com")
    bob.headers["Authorization"] = f"Bearer {signed_in.access_token}"

    response = await bob.delete(f"{CONNECTIONS}/{connected['id']}")

    assert response.status_code == 404, response.text
    assert (await McpClient(app, tokens["access_token"]).send("tools/list")).status_code == 200


async def test_disconnecting_an_app_twice_is_404(
    subscribed, clock, authed_client, app, oauth_client
):
    await connect(authed_client, app, oauth_client)
    [connected] = await listed(authed_client)
    await authed_client.delete(f"{CONNECTIONS}/{connected['id']}")

    response = await authed_client.delete(f"{CONNECTIONS}/{connected['id']}")

    assert response.status_code == 404, response.text


async def test_listing_needs_a_signed_in_user(app):
    assert (await app.get(CONNECTIONS)).status_code == 401


def _connection(user_id: str, client_id: str, clock) -> AppConnection:
    return AppConnection(
        user_id=user_id, client_id=client_id, scope="pumpkit", resource=MCP_URL, created_at=clock()
    )


async def test_a_second_unrevoked_connection_to_the_same_app_is_refused(
    db, user, oauth_client, clock
):
    db.add(_connection(user.id, oauth_client, clock))
    await db.commit()

    db.add(_connection(user.id, oauth_client, clock))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_a_revoked_connection_leaves_room_for_a_new_one(db, user, oauth_client, clock):
    revoked = _connection(user.id, oauth_client, clock)
    revoked.revoked_at = clock()
    db.add(revoked)
    await db.commit()

    db.add(_connection(user.id, oauth_client, clock))
    await db.commit()


async def test_find_or_create_returns_the_connection_a_racing_approval_created(
    db, user, oauth_client, clock
):
    raced: list[str] = []

    # Lets the lookup miss, then creates the row as a concurrent approval would before the insert.
    @event.listens_for(db.sync_session, "do_orm_execute")
    def _race(state: ORMExecuteState):
        if raced or not state.is_select:
            return None
        result = state.invoke_statement()
        raced.append("done")
        state.session.execute(
            insert(AppConnection).values(
                id="app_connection_winner",
                user_id=user.id,
                client_id=oauth_client,
                scope="pumpkit",
                resource=MCP_URL,
                created_at=clock(),
            )
        )
        return result

    connection = await connections.find_or_create(
        db, user_id=user.id, client_id=oauth_client, scope="pumpkit", resource=MCP_URL, now=clock()
    )

    assert connection.id == "app_connection_winner"
    stored = (await db.execute(select(AppConnection.id))).scalars().all()
    assert stored == ["app_connection_winner"]
