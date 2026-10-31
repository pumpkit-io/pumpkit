"""Seed a Subscribed user at the start of Onboarding, and print `E2E_ACCESS_TOKEN=<jwt>`.

The user has no X connection, no Inspiration authors and hasn't finished Onboarding, so it starts
at the X step where the Instance has X, and `connect_x.py` with its email moves it to the Persona
step. The Author directory gets `e2e_author`, whose posts were just fetched, so picking it reuses
them and never calls twitterapi.io, and `e2e_not_on_x` is a remembered miss, so looking
it up answers "isn't on X" without calling twitterapi.io either. Run it like `seed_user.py`.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from pumpkit.auth.models import User
from pumpkit.auth.tokens import create_access_token
from pumpkit.authors.models import (
    MISS_MISSING,
    SOURCE_LOOKUP,
    AuthorDirectoryEntry,
    AuthorFetch,
    AuthorHandleMiss,
    AuthorPost,
    InspirationAuthor,
)
from pumpkit.billing.models import Subscription
from pumpkit.core.db.session import _db_session_handler
from pumpkit.onboarding.models import OnboardingFinish
from pumpkit.x_connection.models import XConnection

E2E_EMAIL = "e2e-onboarding@e2e-user.dev"
AUTHOR = "e2e_author"
MISSING_HANDLE = "e2e_not_on_x"


async def main() -> None:
    now = datetime.now(timezone.utc)
    async with _db_session_handler.async_session_maker() as db:
        user = (await db.execute(select(User).where(User.email == E2E_EMAIL))).scalar_one_or_none()
        if user is None:
            user = User(email=E2E_EMAIL, display_name="E2E Newcomer", first_name="E2E")
            db.add(user)
        await db.flush()

        await db.execute(delete(InspirationAuthor).where(InspirationAuthor.user_id == user.id))
        await db.execute(delete(OnboardingFinish).where(OnboardingFinish.user_id == user.id))
        await db.execute(delete(XConnection).where(XConnection.user_id == user.id))
        held = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
        if held.first() is None:
            db.add(
                Subscription(
                    user_id=user.id,
                    stripe_subscription_id="sub_e2e_onboarding",
                    stripe_customer_id="cus_e2e_onboarding",
                    status="active",
                    stripe_created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                )
            )

        if await db.get(AuthorDirectoryEntry, AUTHOR) is None:
            db.add(
                AuthorDirectoryEntry(
                    handle=AUTHOR, name="E2E Author", added_at=now, source=SOURCE_LOOKUP
                )
            )
        fetch = await db.get(AuthorFetch, AUTHOR)
        if fetch is None:
            db.add(AuthorFetch(handle=AUTHOR, last_fetched_at=now))
        else:
            fetch.last_fetched_at = now
        for i in range(3):
            if await db.get(AuthorPost, f"e2e-author-{i}") is None:
                db.add(
                    AuthorPost(
                        id=f"e2e-author-{i}",
                        handle=AUTHOR,
                        text=f"E2E Author's post number {i}.",
                        posted_at=now - timedelta(days=i + 1),
                        fetched_at=now,
                    )
                )
        miss = await db.get(AuthorHandleMiss, MISSING_HANDLE)
        if miss is None:
            miss = AuthorHandleMiss(handle=MISSING_HANDLE, reason=MISS_MISSING)
            db.add(miss)
        miss.remembered_until = now + timedelta(days=7)
        await db.commit()
        await db.refresh(user)

    print(f"E2E_ACCESS_TOKEN={create_access_token({'sub': user.id})}")


if __name__ == "__main__":
    asyncio.run(main())
