"""Mark the managed browser fixture's publishing authorization as lost."""

import asyncio

from sqlalchemy import select

from pumpkit.auth.models import User
from pumpkit.core.db.session import _db_session_handler
from pumpkit.x_connection.models import XConnection
from tests.browser_seed import x_id_for


async def main() -> None:
    identity = x_id_for("e2e@e2e-user.dev")
    async with _db_session_handler.async_session_maker() as db:
        user = (await db.scalars(select(User).where(User.x_user_id == identity))).one()
        connection = (
            await db.scalars(select(XConnection).where(XConnection.user_id == user.id))
        ).one()
        connection.needs_reconnect = True
        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
