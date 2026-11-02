"""Seed a User with no Subscription and no Stripe customer, named by the email argument, and print `E2E_ACCESS_TOKEN=<jwt>`.

Each test passes an email of its own, so the User starts at the Paywall whatever earlier runs did.
Run it like `seed_user.py`, with the email after `-`.
"""

import asyncio
import sys

from sqlalchemy import select

from pumpkit.auth.models import User
from pumpkit.auth.tokens import create_access_token
from pumpkit.core.db.session import _db_session_handler


async def main(email: str) -> None:
    async with _db_session_handler.async_session_maker() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if user is None:
            user = User(email=email, display_name="E2E Newcomer", first_name="E2E")
            db.add(user)
        await db.commit()
        await db.refresh(user)

    print(f"E2E_ACCESS_TOKEN={create_access_token({'sub': user.id})}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
