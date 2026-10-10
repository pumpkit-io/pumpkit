"""Seed a fixed e2e test user and print one machine-readable line, `E2E_ACCESS_TOKEN=<jwt>`.

The user is Subscribed through a Subscription written straight into Pumpkit's copy, and has
no Inspiration authors, X connection or Scheduled posts, so Home and Scheduled show their
tools without calling any provider.

Run inside the backend container: `docker compose exec -T backend python - < e2e/seed/seed_user.py`.
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.core.security import create_access_token
from app.db.models import InspirationAuthor, ScheduledPost, Subscription, User, XConnection
from app.db.session import _db_session_handler

# Not a `.test`/`.example` TLD: those are special-use and rejected by the
# EmailStr validation in UserProfileResponse.
E2E_EMAIL = "e2e@e2e-user.dev"


async def main() -> None:
    async with _db_session_handler.async_session_maker() as db:
        result = await db.execute(select(User).where(User.email == E2E_EMAIL))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                email=E2E_EMAIL, display_name="E2E User", first_name="E2E", last_name="User"
            )
            db.add(user)
        else:
            user.first_name, user.last_name, user.display_name = "E2E", "User", "E2E User"
        await db.flush()

        await db.execute(delete(InspirationAuthor).where(InspirationAuthor.user_id == user.id))
        await db.execute(delete(XConnection).where(XConnection.user_id == user.id))
        await db.execute(delete(ScheduledPost).where(ScheduledPost.user_id == user.id))
        held = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
        if held.first() is None:
            db.add(
                Subscription(
                    user_id=user.id,
                    stripe_subscription_id="sub_e2e",
                    stripe_customer_id="cus_e2e",
                    status="active",
                    stripe_created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                )
            )
        await db.commit()
        await db.refresh(user)

    print(f"E2E_ACCESS_TOKEN={create_access_token({'sub': user.id})}")


if __name__ == "__main__":
    asyncio.run(main())
