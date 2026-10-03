from sqlalchemy import inspect

from app.db.models import User


async def test_all_tables_create_on_sqlite(db_engine):
    async with db_engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
    assert {"users", "auth_sessions", "subscriptions", "magic_links"} <= set(tables)


async def test_user_fixture_persists(db, user):
    loaded = await db.get(User, user.id)
    assert loaded is not None
    assert loaded.email == "alice@example.com"
