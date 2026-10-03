"""Seed a fixed e2e test user and print a fresh access token.

Run inside the backend container:
    docker compose exec -T backend python - < e2e/seed/seed_user.py

Prints exactly one machine-readable line:
    E2E_ACCESS_TOKEN=<jwt>
"""

import asyncio

from sqlalchemy import select

from app.core.security import create_access_token
from app.db.models import User
from app.db.session import _db_session_handler

# Not a `.test`/`.example` TLD: those are special-use and rejected by the
# EmailStr validation in UserProfileResponse.
E2E_EMAIL = "e2e@e2e-user.dev"


async def main() -> None:
    async with _db_session_handler.async_session_maker() as db:
        result = await db.execute(select(User).where(User.email == E2E_EMAIL))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(email=E2E_EMAIL, display_name="E2E User", first_name="E2E", last_name="User")
            db.add(user)
        else:
            user.first_name, user.last_name, user.display_name = "E2E", "User", "E2E User"
        await db.commit()
        await db.refresh(user)

    print(f"E2E_ACCESS_TOKEN={create_access_token({'sub': user.id})}")


if __name__ == "__main__":
    asyncio.run(main())
