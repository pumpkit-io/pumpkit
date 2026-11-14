"""Seed a Subscribed user at the start of Onboarding, and print `E2E_ACCESS_TOKEN=<jwt>`.

The user has no X connection, no Positioning, no draft requests and hasn't finished Onboarding,
so it starts at the Persona step, where a draft finds no X connection and reads nothing.
`connect_x.py` with its email gives it one. Run it like `seed_user.py`.
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import delete, select

from pumpkit.auth.models import User
from pumpkit.auth.tokens import create_access_token
from pumpkit.billing.models import Subscription
from pumpkit.core.db.session import _db_session_handler
from pumpkit.onboarding.models import OnboardingFinish
from pumpkit.positioning.models import Positioning, PositioningDraftRequest
from pumpkit.x_connection.models import XConnection
from tests.browser_seed import bind_x_identity, x_id_for

E2E_EMAIL = "e2e-onboarding@e2e-user.dev"


async def main() -> None:
    async with _db_session_handler.async_session_maker() as db:
        user = (
            await db.execute(select(User).where(User.x_user_id == x_id_for(E2E_EMAIL)))
        ).scalar_one_or_none()
        if user is None:
            user = User(email=E2E_EMAIL, display_name="E2E Newcomer", first_name="E2E")
            db.add(user)
        bind_x_identity(user)
        await db.flush()

        await db.execute(delete(Positioning).where(Positioning.user_id == user.id))
        await db.execute(
            delete(PositioningDraftRequest).where(PositioningDraftRequest.user_id == user.id)
        )
        await db.execute(delete(OnboardingFinish).where(OnboardingFinish.user_id == user.id))
        await db.execute(delete(XConnection).where(XConnection.user_id == user.id))
        # The Stripe Emulator seeds this customer and Subscription (emulate.config.ts).
        user.stripe_customer_id = "cus_e2e_onboarding"
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

        await db.commit()
        await db.refresh(user)

    print(f"E2E_ACCESS_TOKEN={create_access_token({'sub': user.id})}")


if __name__ == "__main__":
    asyncio.run(main())
