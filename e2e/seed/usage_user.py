"""Seed usage without calling writing, publishing or payment providers; reset this User per test."""

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from pumpkit.auth.models import User
from pumpkit.auth.tokens import create_access_token
from pumpkit.authors.models import AuthorPost, InspirationAuthor
from pumpkit.billing.models import Subscription
from pumpkit.core.config import settings
from pumpkit.core.db.session import _db_session_handler
from pumpkit.onboarding.models import OnboardingFinish
from pumpkit.posts.models import ATTEMPT_SUCCEEDED, Post, VersionAttempt
from pumpkit.posts.service import set_text_from_version
from pumpkit.scheduling.service import create as schedule_post
from pumpkit.x_connection.service import save_connection
from pumpkit.x_connection.x_publisher import XAccount, XTokens

EMAIL = "e2e-usage@e2e-user.dev"
PARTS = ["Read this: https://example.com/usage"]


async def main() -> None:
    if not settings.is_stripe_billing_configured() or not settings.BILLING_TOP_UP_KEY:
        raise RuntimeError(
            "Usage smoke tests need dummy billing and a Top-up key; see CONTRIBUTING.md"
        )
    if (
        settings.GENERATIONS_MONTHLY_CAP,
        settings.X_POSTS_MONTHLY_CAP,
        settings.X_LINK_POSTS_MONTHLY_CAP,
    ) != (500, 100, 10):
        raise RuntimeError(
            "Usage smoke tests need caps 500/100/10; see CONTRIBUTING.md"
        )
    scenario = sys.argv[1]
    trial = scenario == "trial"
    used = 500 if scenario == "limit" else 3
    now = datetime.now(timezone.utc)
    anchor = now - timedelta(days=2)
    # Old enough to avoid the hourly writing-attempt limit, inside this Allowance period.
    written_at = now - timedelta(hours=2)
    async with _db_session_handler.async_session_maker() as db:
        await db.execute(delete(User).where(User.email == EMAIL))
        user = User(email=EMAIL, display_name="E2E Usage")
        db.add(user)
        await db.flush()
        db.add_all(
            [
                OnboardingFinish(user_id=user.id, finished_at=anchor),
                Subscription(
                    user_id=user.id,
                    stripe_subscription_id="sub_e2e_usage",
                    stripe_customer_id="cus_e2e_usage",
                    plan_key="pumpkit_pro_monthly",
                    status="trialing" if trial else "active",
                    stripe_created_at=anchor,
                    billing_cycle_anchor=anchor,
                    trial_start=anchor if trial else None,
                    trial_end=now + timedelta(days=5) if trial else None,
                    current_period_end=now + timedelta(days=5 if trial else 28),
                ),
                InspirationAuthor(
                    user_id=user.id, handle="e2e_usage", position=0, added_at=anchor
                ),
            ]
        )
        if await db.get(AuthorPost, "e2e-usage-author-post") is None:
            db.add(
                AuthorPost(
                    id="e2e-usage-author-post",
                    handle="e2e_usage",
                    text="A locally seeded post.",
                    posted_at=anchor,
                    fetched_at=now,
                )
            )
        await save_connection(
            db,
            user_id=user.id,
            account=XAccount(
                user_id="e2e-x-usage", handle="e2e_usage", subscription_type="None"
            ),
            tokens=XTokens(
                access_token="e2e-access",
                refresh_token="e2e-refresh",
                expires_at=now + timedelta(hours=2),
                scope="tweet.read tweet.write users.read offline.access",
            ),
            now=now,
        )
        post = Post(
            user_id=user.id,
            brief="E2E usage",
            corpus_post_ids=[],
            created_at=written_at,
        )
        db.add(post)
        for number in range(1, used + 1):
            version = VersionAttempt(
                post=post,
                sequence=number,
                version_number=number,
                format="post",
                status=ATTEMPT_SUCCEEDED,
                sketch_parts=PARTS,
                parts=PARTS,
                created_at=written_at,
            )
            db.add(version)
            set_text_from_version(post, version)
        scheduled = Post(
            user_id=user.id,
            brief="E2E reserved usage",
            corpus_post_ids=[],
            created_at=anchor - timedelta(days=1),
        )
        version = VersionAttempt(
            post=scheduled,
            sequence=1,
            version_number=1,
            format="post",
            status=ATTEMPT_SUCCEEDED,
            sketch_parts=PARTS,
            parts=PARTS,
            created_at=anchor - timedelta(days=1),
        )
        set_text_from_version(scheduled, version)
        db.add_all([scheduled, version])
        await db.flush()
        await schedule_post(
            db,
            user_id=user.id,
            x_user_id="e2e-x-usage",
            post_id=scheduled.id,
            parts=PARTS,
            publish_at=now + timedelta(hours=1),
            now=now,
        )
        await db.commit()
        print(
            "E2E_USAGE="
            + json.dumps(
                {
                    "token": create_access_token({"sub": user.id}),
                    "postId": post.id,
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
