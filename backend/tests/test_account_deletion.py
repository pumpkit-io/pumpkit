"""
A User deleting their own account from Settings with `DELETE /users/me` (ADR 0031): confirmed by
their handle, ending a Running Subscription at once, refused while something is in flight, and
followed by revoking Pumpkit's X grant.
"""

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO, StringIO

import pytest
from sqlalchemy import event, select

from pumpkit.account_deletion import delete_files, run_cli
from pumpkit.account_deletion_router import router as account_deletion_router
from pumpkit.auth.models import User
from pumpkit.billing.gateway import BillingProviderError, SubscriptionState
from pumpkit.billing.models import Subscription
from pumpkit.billing.subscription_status import SubscriptionStatus
from pumpkit.core.background import get_background_tasks
from pumpkit.core.db.session import get_session_maker
from pumpkit.core.storage import get_file_storage
from pumpkit.posts.models import AccountFileDeletion, Media
from pumpkit.scheduling.models import PUBLISHING, ScheduledPost
from pumpkit.x_connection.models import XConnection
from tests.billing.paid_signups import open_paid_signup
from tests.billing.test_billing import CHECKOUT, CHECKOUT_MONTHLY
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_trial_eligibility import BILLING_ME, ended_trial, sign_in
from tests.billing.test_trial_eligibility import trial_app as trial_app
from tests.billing.test_trial_eligibility import trial_browser as trial_browser
from tests.billing.test_trial_eligibility import trial_keys as trial_keys
from tests.conftest import InlineTasks
from tests.mcp_client import McpClient
from tests.x_connection.sign_in.conftest import sign_in_app as sign_in_app

DELETE_ME = "/api/v1/users/me"
NOW = datetime(2026, 11, 15, tzinfo=timezone.utc)
NOT_ENDED = {"detail": "Couldn't end your subscription. Try again, or contact support."}


@pytest.fixture(autouse=True)
async def enforce_account_cascades(db_engine):
    if db_engine.dialect.name == "sqlite":

        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        event.listen(db_engine.sync_engine, "connect", foreign_keys)


async def delete_me(browser, handle="@ada"):
    return await browser.request("DELETE", DELETE_ME, json={"handle": handle})


async def user_exists(db, user) -> bool:
    return await db.scalar(select(User.id).where(User.id == user.id)) is not None


@pytest.mark.parametrize("handle", ["@ada", "ada", "@ADA", " Ada "])
async def test_confirming_with_the_handle_deletes_the_account(authed_client, db, user, handle):
    response = await delete_me(authed_client, handle)

    assert response.status_code == 204, response.text
    assert not await user_exists(db, user)


async def test_a_wrong_handle_deletes_nothing(authed_client, db, user):
    response = await delete_me(authed_client, "@grace")

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "handle_mismatch"
    assert await user_exists(db, user)


async def test_deleting_clears_the_refresh_cookie_and_ends_every_session(
    authed_client, new_browser, sign_in_for_test, user
):
    other_browser = new_browser()
    await sign_in_for_test(other_browser, user.email)

    response = await delete_me(authed_client)

    assert response.status_code == 204, response.text
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert (await other_browser.post("/api/v1/refresh-token")).status_code == 401
    assert (await authed_client.get("/api/v1/users/me")).status_code == 401


async def test_a_connected_apps_token_stops_working(sells_no_plans, authed_client, mcp: McpClient):
    assert (await mcp.send("tools/list")).status_code == 200

    assert (await delete_me(authed_client)).status_code == 204

    assert (await mcp.send("tools/list")).status_code == 401


async def test_deleting_revokes_the_x_grant_read_before_the_cascade(
    authed_client, db, user, connect_x, fake_x_publisher
):
    await connect_x()

    assert (await delete_me(authed_client)).status_code == 204

    assert fake_x_publisher.revoked == [f"refresh-{fake_x_publisher.account.user_id}-1"]
    assert await db.scalar(select(XConnection.id)) is None


async def test_a_failed_revoke_still_deletes(authed_client, db, user, connect_x, fake_x_publisher):
    await connect_x()
    fake_x_publisher.fail_revoke = True

    assert (await delete_me(authed_client)).status_code == 204

    assert not await user_exists(db, user)


async def test_deleting_removes_the_media_files(authed_client, db, user, file_storage):
    await file_storage.put("media/ada/photo", BytesIO(b"photo"))
    db.add(
        Media(
            user_id=user.id,
            kind="image",
            content_type="image/png",
            byte_size=5,
            file_key="media/ada/photo",
            created_at=NOW,
        )
    )
    await db.commit()

    assert (await delete_me(authed_client)).status_code == 204

    assert await file_storage.list_files("media") == []


async def test_deleting_leaves_another_accounts_queued_files(authed_client, db, user, file_storage):
    await file_storage.put("media/grace/photo", BytesIO(b"photo"))
    db.add(AccountFileDeletion(key="media/grace/photo"))
    await db.commit()

    assert (await delete_me(authed_client)).status_code == 204

    assert [f.key for f in await file_storage.list_files("media")] == ["media/grace/photo"]


async def test_a_post_going_out_on_x_refuses_deletion(authed_client, db, user, post_with):
    post_id = await post_with("Going out now.")
    db.add(
        ScheduledPost(
            user_id=user.id,
            x_user_id="1001",
            publish_at=NOW,
            state=PUBLISHING,
            post_id=post_id,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    await db.commit()

    response = await delete_me(authed_client)

    assert response.status_code == 409, response.text
    assert response.json() == {
        "detail": "A post is going out on X right now. Try again in a minute.",
        "code": "publishing_in_progress",
    }
    assert await user_exists(db, user)


async def test_deleting_expires_an_open_checkout(authed_client, db, user, fake_billing):
    user.stripe_customer_id = "cus_ada"
    await db.commit()
    await fake_billing.create_subscription_checkout(
        customer_id="cus_ada", price_id="price_monthly", quantity=1, user_id=user.id
    )

    assert (await delete_me(authed_client)).status_code == 204

    assert fake_billing.expired_checkouts == ["cs_fake_1"]
    assert not await user_exists(db, user)


async def test_a_pending_paid_signup_doesnt_hold_up_deletion(
    authed_client, db, user, coupons, fake_billing, fixed_clock
):
    fake_billing.clock = fixed_clock
    _, _, opened = await open_paid_signup(authed_client, coupons)

    assert (await delete_me(authed_client)).status_code == 204

    assert fake_billing.paid_signup_checkouts[opened["session_id"]].status == "expired"
    assert not await user_exists(db, user)


async def test_an_unpaid_invoice_refuses_deletion(authed_client, db, user, fake_billing):
    user.stripe_customer_id = "cus_ada"
    await db.commit()
    fake_billing.unsettled_invoice_customers.add("cus_ada")

    response = await delete_me(authed_client)

    assert response.status_code == 409, response.text
    assert response.json() == {
        "detail": "You have an unpaid invoice. Contact support to delete your account.",
        "code": "unpaid_invoice",
    }
    assert await user_exists(db, user)


async def running_subscription(
    db, user, fake_billing, status: SubscriptionStatus = "active"
) -> None:
    user.stripe_customer_id = "cus_ada"
    await db.commit()
    stripe_subscription(fake_billing, "cus_ada", "sub_ada", status)


def stripe_subscription(
    fake_billing, customer_id: str, subscription_id: str, status: SubscriptionStatus = "active"
) -> None:
    fake_billing.set_subscription(
        customer_id,
        SubscriptionState(
            id=subscription_id,
            status=status,
            price_id="price_monthly",
            plan_key="pumpkit_pro_monthly",
            current_period_end=datetime(2026, 12, 1, tzinfo=timezone.utc),
            created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
        ),
    )


@pytest.mark.parametrize("status", ["active", "trialing", "past_due"])
async def test_deleting_ends_a_running_subscription_at_once(
    authed_client, db, user, fake_billing, status
):
    await running_subscription(db, user, fake_billing, status)

    assert (await delete_me(authed_client)).status_code == 204

    assert fake_billing.cancelled_subscriptions == ["sub_ada"]
    assert not await user_exists(db, user)


async def test_an_unpaid_invoice_refuses_before_ending_the_subscription(
    authed_client, db, user, fake_billing
):
    await running_subscription(db, user, fake_billing, "past_due")
    fake_billing.unsettled_invoice_customers.add("cus_ada")

    response = await delete_me(authed_client)

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "unpaid_invoice"
    assert fake_billing.cancelled_subscriptions == []
    assert await user_exists(db, user)


@pytest.mark.parametrize("failing", ["cancel_subscription", "expire_open_checkouts"])
async def test_stripe_failing_to_end_billing_deletes_nothing(
    authed_client, db, user, fake_billing, failing
):
    await running_subscription(db, user, fake_billing)
    fake_billing.fail_on.add(failing)

    response = await delete_me(authed_client)

    assert response.status_code == 502, response.text
    assert response.json()["detail"] == (
        "Couldn't end your subscription. Try again, or contact support."
    )
    assert await user_exists(db, user)


async def test_a_running_subscription_stripe_doesnt_list_deletes_nothing(
    authed_client, db, user, subscribed: Subscription
):
    response = await delete_me(authed_client)

    assert response.status_code == 502, response.text
    assert response.json()["detail"] == NOT_ENDED["detail"]
    assert await user_exists(db, user)


async def test_a_pending_checkout_that_survives_expiry_refuses_before_ending_anything(
    authed_client, db, user, fake_billing
):
    await running_subscription(db, user, fake_billing)
    fake_billing.set_top_up_payment_pending(
        customer_id="cus_ada", checkout_session_id="cs_top_up_delayed"
    )

    response = await delete_me(authed_client)

    assert response.status_code == 409, response.text
    assert response.json() == {
        "detail": "A billing change is still being processed. Try again in a few minutes.",
        "code": "billing_operation_pending",
    }
    assert fake_billing.cancelled_subscriptions == []
    assert await user_exists(db, user)


async def test_a_retry_after_stripe_failed_partway_through_the_cancels_deletes(
    authed_client, db, user, fake_billing, monkeypatch
):
    await running_subscription(db, user, fake_billing)
    db.add(
        Subscription(
            user_id=user.id,
            stripe_subscription_id="sub_ada_2",
            stripe_customer_id="cus_ada_2",
            status="active",
            stripe_created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    )
    await db.commit()
    stripe_subscription(fake_billing, "cus_ada_2", "sub_ada_2")
    cancel = fake_billing.cancel_subscription

    async def fail_on_the_second(*, subscription_id: str) -> None:
        if subscription_id == "sub_ada_2":
            raise BillingProviderError("Stripe is down")
        await cancel(subscription_id=subscription_id)

    monkeypatch.setattr(fake_billing, "cancel_subscription", fail_on_the_second)

    response = await delete_me(authed_client)

    assert response.status_code == 502, response.text
    assert response.json()["detail"] == NOT_ENDED["detail"]
    assert fake_billing.cancelled_subscriptions == ["sub_ada"]
    assert await user_exists(db, user)

    monkeypatch.setattr(fake_billing, "cancel_subscription", cancel)

    assert (await delete_me(authed_client)).status_code == 204
    assert fake_billing.cancelled_subscriptions == ["sub_ada", "sub_ada_2"]
    assert (await authed_client.get("/api/v1/users/me")).status_code == 401


async def test_a_subscription_stripe_still_lists_after_its_cancel_answers_502(
    authed_client, db, user, fake_billing, monkeypatch
):
    await running_subscription(db, user, fake_billing)

    async def cancel_that_leaves_it_running(*, subscription_id: str) -> None:
        pass

    monkeypatch.setattr(fake_billing, "cancel_subscription", cancel_that_leaves_it_running)

    response = await delete_me(authed_client)

    assert response.status_code == 502, response.text
    assert response.json()["detail"] == NOT_ENDED["detail"]
    assert await user_exists(db, user)


async def test_the_operator_command_refuses_a_running_subscription(
    db, db_session_maker, user, fake_billing, file_storage
):
    await running_subscription(db, user, fake_billing)
    errors = StringIO()

    result = await run_cli(
        ["--user-id", user.id],
        sessions=db_session_maker,
        gateway=fake_billing,
        storage=file_storage,
        stdout=StringIO(),
        stderr=errors,
    )

    assert result == 1
    assert errors.getvalue() == (
        "Resolve outstanding subscription and payment obligations before deleting this account.\n"
    )
    assert fake_billing.cancelled_subscriptions == []
    assert await user_exists(db, user)


@pytest.fixture
def deleting_trial_app(trial_app, db_session_maker, file_storage):
    trial_app.include_router(account_deletion_router, prefix="/api/v1")
    trial_app.dependency_overrides[get_background_tasks] = InlineTasks
    trial_app.dependency_overrides[get_session_maker] = lambda: db_session_maker
    trial_app.dependency_overrides[get_file_storage] = lambda: file_storage
    return trial_app


async def test_signing_in_again_after_ending_a_trial_makes_a_new_account_with_no_trial(
    deleting_trial_app, trial_browser, fake_x_publisher, fake_billing, fixed_clock
):
    original = await sign_in(trial_browser, fake_x_publisher)
    assert (await trial_browser.post(CHECKOUT, json=CHECKOUT_MONTHLY)).status_code == 200
    customer = fake_billing.checkouts[-1].customer_id
    fake_billing.set_subscription(customer, replace(ended_trial(fixed_clock), status="trialing"))

    assert (await delete_me(trial_browser)).status_code == 204

    assert fake_billing.cancelled_subscriptions == ["sub_used_trial"]
    recreated = await sign_in(trial_browser, fake_x_publisher)
    assert recreated["id"] != original["id"]
    offer = (await trial_browser.get(BILLING_ME)).json()
    assert offer["trial_days"] is None


async def test_two_accounts_sweeps_each_delete_their_own_files(db, db_session_maker, file_storage):
    await file_storage.put("media/ada/photo", BytesIO(b"ada"))
    await file_storage.put("media/grace/photo", BytesIO(b"grace"))
    db.add_all(
        [AccountFileDeletion(key="media/ada/photo"), AccountFileDeletion(key="media/grace/photo")]
    )
    await db.commit()

    for key in ("media/grace/photo", "media/ada/photo"):
        async with db_session_maker() as sweeping:
            await delete_files(sweeping, file_storage, only_keys=frozenset({key}))

    assert await file_storage.list_files("media") == []
    assert await db.scalar(select(AccountFileDeletion.key)) is None


async def test_the_x_revoke_doesnt_hold_up_the_deletion(
    authed_client, db, user, connect_x, fake_x_publisher, background_tasks, monkeypatch
):
    await connect_x()
    release = asyncio.Event()
    revoke = fake_x_publisher.revoke

    async def slow_revoke(**kwargs):
        await asyncio.wait_for(release.wait(), 10)
        await revoke(**kwargs)

    monkeypatch.setattr(fake_x_publisher, "revoke", slow_revoke)

    assert (await delete_me(authed_client)).status_code == 204
    assert fake_x_publisher.revoked == []

    release.set()
    await background_tasks.wait()
    assert fake_x_publisher.revoked == [f"refresh-{fake_x_publisher.account.user_id}-1"]


async def test_a_failed_revoke_logs_no_token(
    authed_client, user, connect_x, fake_x_publisher, caplog
):
    await connect_x()
    fake_x_publisher.fail_revoke = True

    assert (await delete_me(authed_client)).status_code == 204

    assert "Revoking a deleted account's X token failed" in caplog.text
    assert f"refresh-{fake_x_publisher.account.user_id}" not in caplog.text
