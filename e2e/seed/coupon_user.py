"""Create isolated coupon journey users against this worktree's local Stripe Emulator."""

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy import select

from pumpkit.auth.models import User
from pumpkit.auth.tokens import create_access_token
from pumpkit.billing import coupon_service, service
from pumpkit.billing.gateway import get_billing_gateway
from pumpkit.billing.models import FreeAccess
from pumpkit.billing.schemas import CouponIssueRequest
from pumpkit.core.config import settings
from pumpkit.core.db.session import _db_session_handler
from pumpkit.onboarding.models import OnboardingFinish


def require_emulator() -> None:
    if (
        not settings.COUPONS_ENABLED
        or not settings.is_operator_configured()
        or urlparse(settings.STRIPE_API_URL or "").hostname != "emulate"
        or settings.STRIPE_SECRET_KEY != "sk_test_dev"
        or settings.STRIPE_COUPON_PORTAL_CONFIGURATION_ID != "bpc_coupon_management"
    ):
        raise RuntimeError(
            "Coupon journeys require the isolated local Emulator configuration."
        )


async def main() -> None:
    require_emulator()
    action = sys.argv[1]
    if action == "check":
        return
    now = datetime.now(timezone.utc).replace(microsecond=0)
    async with _db_session_handler.async_session_maker() as db:
        if action in {"finish", "expire"}:
            user = await db.scalar(select(User).where(User.email == sys.argv[2]))
            assert user is not None
            if action == "finish":
                if await db.get(OnboardingFinish, user.id) is None:
                    db.add(OnboardingFinish(user_id=user.id, finished_at=now))
            else:
                access = await db.scalar(
                    select(FreeAccess).where(FreeAccess.user_id == user.id)
                )
                assert access is not None
                assert user.stripe_customer_id is None
                access.starts_at = now - timedelta(days=40)
                access.coverage_starts_at = access.starts_at
                access.calendar_anchor = access.starts_at
                access.ends_at = now - timedelta(days=1)
            await db.commit()
            return
        email = f"e2e-coupon-{uuid4().hex}@e2e-user.dev"
        user = User(email=email, display_name="E2E Coupon", first_name="E2E")
        db.add(user)
        await db.flush()
        if action.startswith("subscriber-"):
            gateway = get_billing_gateway()
            customer = await gateway.create_customer(
                email=email,
                name="E2E Coupon",
                user_id=user.id,
                idempotency_key=uuid4().hex,
            )
            user.stripe_customer_id = customer
            await db.commit()
            plan_key = (
                "pumpkit_pro_yearly"
                if action.endswith("year")
                else "pumpkit_pro_monthly"
            )
            plan = (await gateway.list_plans([plan_key]))[0]
            checkout = await gateway.create_subscription_checkout(
                customer_id=customer,
                price_id=plan.price_id,
                quantity=1,
                user_id=user.id,
                trial_period_days=None,
            )
            async with httpx.AsyncClient() as client:
                result = await client.post(
                    settings.STRIPE_API_URL + "/checkout/" + checkout.id + "/pay"
                )
                assert result.status_code == 303
            await service.sync_customer(
                db, gateway, user_id=user.id, customer_id=customer
            )
            db.add(OnboardingFinish(user_id=user.id, finished_at=now))
        elif action != "new":
            raise ValueError("Unknown coupon journey")
        _, code = await coupon_service.issue(
            db,
            request=CouponIssueRequest(months=1, recipient=email),
            config=settings,
            now=now,
        )
        await db.commit()
        print(
            "E2E_COUPON="
            + json.dumps(
                {
                    "token": create_access_token({"sub": user.id}),
                    "email": email,
                    "code": code,
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
