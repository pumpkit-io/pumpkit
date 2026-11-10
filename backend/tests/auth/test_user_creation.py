import pytest
from sqlalchemy import MetaData, Table, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from pumpkit.auth.models import User
from pumpkit.auth.service import users
from pumpkit.core.errors import ForbiddenError


async def test_creating_a_user_initializes_names_and_can_be_rolled_back(db):
    created = await users.create_user(
        db,
        "  Alice@Example.com  ",
        users.NameHints(first_name="Alice", last_name="Liddell", display_name="Alice Liddell"),
    )

    assert created.id.startswith("user_")
    assert created.email == "alice@example.com"
    assert created.first_name == "Alice"
    assert created.last_name == "Liddell"
    assert created.display_name == "Alice Liddell"
    assert created.is_admin is False
    user_id = created.id
    await db.rollback()
    assert await users.get_user_by_id(db, user_id) is None


async def test_creating_without_name_hints_uses_the_normalized_email_local_part(db):
    created = await users.create_user(db, "  ALICE@Example.com  ")

    assert created.email == "alice@example.com"
    assert created.display_name == "alice"
    assert created.first_name is None
    assert created.last_name is None


async def test_legacy_email_resolution_refuses_ambiguous_users():
    metadata = MetaData()
    source_table = User.__table__
    assert isinstance(source_table, Table)
    table = source_table.to_metadata(metadata)
    for constraint in list(table.constraints):
        if isinstance(constraint, UniqueConstraint):
            table.constraints.remove(constraint)
    engine = create_async_engine("sqlite+aiosqlite://")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        async with AsyncSession(engine) as db:
            await users.create_user(db, "alice@example.com", users.NameHints(display_name="Alice"))
            await users.create_user(db, "alice@example.com", users.NameHints(display_name="Other"))

            with pytest.raises(ForbiddenError, match="email.*more than one account"):
                await users.resolve_user_by_verified_email(db, "Alice@Example.com")
    finally:
        await engine.dispose()
