"""A User has at most one unrevoked connection to each app, even when two approvals race."""

import pytest
from sqlalchemy import event, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import ORMExecuteState

from pumpkit.connected_apps.models import AppConnection
from pumpkit.connected_apps.service import connections
from tests.connected_apps.conftest import MCP_URL


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
