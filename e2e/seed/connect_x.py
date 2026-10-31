"""Give the seeded e2e user an X connection, so "Post to…" lets them schedule.

Its tokens are fakes: nothing in the smoke tests reaches X, and `seed_user.py` removes the
connection again on the next run. Run it like `seed_user.py`, after it. An email argument
connects that seeded user instead, as `onboarding_user.py`'s to pass the X step.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import pumpkit.x_connection.service as x_connections_service
from pumpkit.auth.models import User
from pumpkit.core.db.session import _db_session_handler
from pumpkit.x_connection.x_publisher import XAccount, XTokens

# X account ids are unique across Users, so each seeded user gets its own X account.
ACCOUNTS = {
    "e2e@e2e-user.dev": ("e2e-x-user", "e2e_user"),
    "e2e-onboarding@e2e-user.dev": ("e2e-x-onboarding", "e2e_newcomer"),
}
E2E_EMAIL = sys.argv[1] if len(sys.argv) > 1 else "e2e@e2e-user.dev"
X_USER_ID, HANDLE = ACCOUNTS[E2E_EMAIL]


async def main() -> None:
    now = datetime.now(timezone.utc)
    async with _db_session_handler.async_session_maker() as db:
        user = (await db.execute(select(User).where(User.email == E2E_EMAIL))).scalar_one()
        await x_connections_service.save_connection(
            db,
            user_id=user.id,
            account=XAccount(user_id=X_USER_ID, handle=HANDLE, subscription_type="None"),
            tokens=XTokens(
                access_token="e2e-access",
                refresh_token="e2e-refresh",
                expires_at=now + timedelta(hours=2),
                scope="tweet.read tweet.write users.read offline.access",
            ),
            now=now,
        )
        await db.commit()


if __name__ == "__main__":
    asyncio.run(main())
