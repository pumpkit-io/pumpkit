"""Seed a User with no Subscription or Stripe customer and print `E2E_ACCESS_TOKEN=<jwt>`.

Run it like `seed_user.py`, with an email of the test's own after `-`, so it starts at the Paywall.
"""

import asyncio
import sys

from sqlalchemy import select

from pumpkit.auth.models import User
from pumpkit.auth.tokens import create_access_token
from pumpkit.core.db.session import _db_session_handler
from tests.browser_seed import bind_x_identity, x_id_for


async def main(email: str) -> None:
    async with _db_session_handler.async_session_maker() as db:
        user = (
            await db.execute(select(User).where(User.x_user_id == x_id_for(email)))
        ).scalar_one_or_none()
        if user is None:
            user = User(email=email, display_name="E2E Newcomer", first_name="E2E")
            db.add(user)
        bind_x_identity(user)
        await db.commit()
        await db.refresh(user)

    print(f"E2E_ACCESS_TOKEN={create_access_token({'sub': user.id})}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
