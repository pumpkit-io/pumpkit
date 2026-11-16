"""
Delete the account an earlier run left for Leaver (X ID 1004), whom the account deletion and
sign-in draft journeys sign in as, ending their Subscriptions through this stack's Stripe
Emulator first.
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
        if user.stripe_customer_id:
            for state in await gateway.list_subscriptions(customer_id=user.stripe_customer_id):
                if state.status not in {"canceled", "incomplete_expired"}:
                    await gateway.cancel_subscription(subscription_id=state.id)
            await gateway.expire_open_checkouts(customer_id=user.stripe_customer_id)
        await account_deletion.delete_account(db, gateway, user_id=user.id)
        await account_deletion.delete_files(db, get_file_storage())


if __name__ == "__main__":
    asyncio.run(main())
