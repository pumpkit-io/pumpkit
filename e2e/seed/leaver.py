"""
Delete the account an earlier run left for Leaver (X ID 1004), whom the account deletion and
sign-in draft journeys sign in as, ending their billing through this stack's Stripe Emulator
as deleting from Settings does.
"""

import asyncio

from sqlalchemy import select

from pumpkit import account_deletion
from pumpkit.auth.models import User
from pumpkit.billing.gateway import get_billing_gateway
from pumpkit.core.db.session import _db_session_handler
from pumpkit.core.storage import get_file_storage
from tests.browser_seed import x_id_for

LEAVER_X_ID = "1004"


async def main() -> None:
    # Refuses to run outside the managed local stack.
    x_id_for("leaver@e2e-user.dev")
    gateway = get_billing_gateway()
    async with _db_session_handler.async_session_maker() as db:
        user = await db.scalar(select(User).where(User.x_user_id == LEAVER_X_ID))
        if user is None:
            return
        # Ends billing as Settings does: the operator path refuses a failed run's pending signup.
        await account_deletion.delete_account(db, gateway, user_id=user.id, end_billing=True)
        await account_deletion.delete_files(db, get_file_storage())


if __name__ == "__main__":
    asyncio.run(main())
