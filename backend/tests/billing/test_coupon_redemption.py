import asyncio
import json
from datetime import datetime, timedelta, timezone
from io import StringIO

import pytest
from pydantic import SecretStr

from pumpkit.account_deletion import run_cli
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.billing.terms import TERMS_VERSION
from pumpkit.core.config import settings
from pumpkit.scheduling.publisher import run_pass
from tests.billing.test_coupon_preview import KEYS
from tests.billing.test_coupon_preview import coupons as coupons
from tests.mcp_client import McpClient
from tests.media_files import png
from tests.oauth_app import REDIRECT, approved_code, exchange, register
from tests.posts.writing_replies import written

PREVIEW = "/api/v1/billing/coupons/preview"
REDEEM = "/api/v1/billing/coupons/redemptions"


def confirmation(preview, operation="redeem-test-0001"):
    return {
        "operation_id": operation,
        "revision": preview["revision"],
        "terms_version": preview["terms_version"],
        "accepted_terms": True,
        "approved_specific_clauses": True,
        "language": "en",
    }


async def test_cardless_confirmation_replays_and_expires_without_provider_commitment(
    client, coupons, fixed_clock, fake_billing
):
    fixed_clock.advance(datetime(2028, 1, 31, 12, tzinfo=timezone.utc) - fixed_clock())
    created = await coupons()
    preview = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    fixed_clock.advance(timedelta(minutes=1))
    response = await client.post(REDEEM, json=confirmation(preview))
    assert response.status_code == 200, response.text
    assert response.json()["ends_at"] == "2028-04-30T12:01:00Z"
    me = (await client.get("/api/v1/billing/me")).json()
    assert me["subscribed"] and me["subscription"] is None
    assert me["may_subscribe"] is False
    assert (await client.get("/api/v1/onboarding")).json()["next_step"] != "paywall"
    fixed_clock.advance(timedelta(days=100))
    assert (await client.post(REDEEM, json=confirmation(preview))).json() == response.json()
    assert (await client.get(REDEEM + "/redeem-test-0001")).json() == response.json()
    assert (await client.get("/api/v1/billing/me")).json()["subscribed"] is False
    assert (await client.get("/api/v1/billing/me")).json()["trial_days"] is None
    assert (await client.get("/api/v1/onboarding")).json()["next_step"] == "paywall"
    assert fake_billing.checkouts == []
    fixed_clock.advance(timedelta(days=90))
    await coupons(command="purge")
    assert (await client.get(REDEEM + "/redeem-test-0001")).status_code == 404
    assert (await client.get("/api/v1/billing/me")).json()["trial_days"] is None


@pytest.mark.parametrize("change", ["disabled", "terms", "allowance", "expired"])
async def test_confirmation_revalidates_without_consuming(
    client, coupons, fixed_clock, monkeypatch, change
):

    created = await coupons()
    preview = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    request = confirmation(preview)
    if change == "disabled":
        await coupons(created["id"], command="disable")
    elif change == "terms":
        request["terms_version"] = "old"
    elif change == "allowance":
        monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 1000)
    else:
        fixed_clock.advance(timedelta(minutes=10))
    assert (await client.post(REDEEM, json=request)).status_code == 409
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0


async def test_free_months_reset_on_original_anchor_and_known_horizon_is_enforced(
    client, coupons, fixed_clock
):
    fixed_clock.advance(datetime(2028, 1, 31, 12, tzinfo=timezone.utc) - fixed_clock())
    created = await coupons()
    preview = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await client.post(REDEEM, json=confirmation(preview))).status_code == 200
    fixed_clock.advance(timedelta(days=30))
    usage = (await client.get("/api/v1/usage")).json()
    assert usage["allowance"]["resets_at"] == "2028-03-31T12:00:00Z"


async def test_two_operations_cannot_claim_same_identity_or_stack_free_time(client, coupons):
    created = await coupons("--max-redemptions", "10")
    preview = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await client.post(REDEEM, json=confirmation(preview))).status_code == 200
    assert (
        await client.post(REDEEM, json=confirmation(preview, "different-operation-02"))
    ).status_code == 409
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 1
    assert (await client.post(PREVIEW, json={"code": created["code"]})).status_code == 409


async def test_deletion_preserves_claim_then_purge_removes_identity_without_restoring_capacity(
    authed_client,
    coupons,
    db_session_maker,
    user,
    fake_billing,
    file_storage,
    fixed_clock,
    new_browser,
    sign_in_by_magic_link,
):

    client = authed_client

    created = await coupons("--max-redemptions", "2")
    preview = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await client.post(REDEEM, json=confirmation(preview))).status_code == 200
    status = await run_cli(
        ["--user-id", user.id],
        sessions=db_session_maker,
        gateway=fake_billing,
        storage=file_storage,
        stdout=StringIO(),
        stderr=StringIO(),
    )
    assert status == 0
    browser = new_browser()
    signed_in = await sign_in_by_magic_link(browser, "alice@example.com")
    browser.headers["Authorization"] = "Bearer " + signed_in.access_token
    refused = await browser.post(PREVIEW, json={"code": created["code"]})
    assert refused.status_code == 409
    assert "already redeemed" in refused.json()["detail"]
    await coupons(created["id"], command="disable")
    fixed_clock.advance(timedelta(days=30))
    await coupons(command="purge")
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 1


async def test_saved_card_former_customer_gets_free_access_without_a_subscription(
    client, coupons, user, db, fake_billing
):
    user.stripe_customer_id = "cus_former"
    await db.commit()
    created = await coupons()
    offer = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await client.post(REDEEM, json=confirmation(offer))).status_code == 200
    assert fake_billing.checkouts == []
    assert fake_billing.expired_checkouts == []


async def test_open_paid_checkout_blocks_claim_without_mutating_it(
    client, coupons, user, db, fake_billing
):
    created = await coupons()
    offer = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    user.stripe_customer_id = "cus_checkout"
    await db.commit()
    await fake_billing.create_subscription_checkout(
        customer_id="cus_checkout",
        price_id="price_monthly",
        quantity=1,
        user_id=user.id,
        trial_period_days=7,
    )
    response = await client.post(REDEEM, json=confirmation(offer))
    assert response.status_code == 409
    assert "pending paid checkout" in response.json()["detail"]
    assert fake_billing.expired_checkouts == []
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0


async def test_exact_expiry_agrees_across_browser_and_connected_app_gates(
    authed_client, coupons, fixed_clock, new_browser
):
    client = authed_client
    created = await coupons("--months", "1")
    offer = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    result = (await client.post(REDEEM, json=confirmation(offer))).json()
    fixed_clock.advance(
        datetime.fromisoformat(result["ends_at"].replace("Z", "+00:00"))
        - fixed_clock()
        - timedelta(microseconds=1)
    )
    app_browser = new_browser()
    client_id = await register(app_browser, REDIRECT, client_name="Coupon test")
    code = await approved_code(client, app_browser, client_id)
    token_response = await exchange(app_browser, client_id, code)
    mcp = McpClient(app_browser, token_response.json()["access_token"])
    assert (await mcp.call_tool("manage_subscription"))["isError"] is False
    assert (await client.get("/api/v1/billing/me")).json()["subscribed"] is True
    fixed_clock.advance(timedelta(microseconds=1))
    assert (await client.get("/api/v1/billing/me")).json()["subscribed"] is False
    assert (await client.get("/api/v1/usage")).status_code == 403
    assert (await mcp.call_tool("manage_subscription"))["isError"] is True


async def test_cardless_scheduling_refuses_at_known_end_and_publisher_fails_at_expiry(
    client,
    coupons,
    fixed_clock,
    connect_x,
    post_with,
    db_session_maker,
    fake_x_publisher,
    file_storage,
):

    fixed_clock.advance(timedelta(seconds=-30))
    created = await coupons("--months", "1")
    offer = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    result = (await client.post(REDEEM, json=confirmation(offer))).json()
    await connect_x()
    post_id = await post_with("Free access schedule")
    end = datetime.fromisoformat(result["ends_at"].replace("Z", "+00:00"))
    refused = await client.post(
        "/api/v1/scheduled-posts", json={"post_id": post_id, "publish_at": end.isoformat()}
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "SUBSCRIPTION_ENDS"
    accepted = await client.post(
        "/api/v1/scheduled-posts",
        json={"post_id": post_id, "publish_at": (end - timedelta(minutes=1)).isoformat()},
    )
    assert accepted.status_code == 201, accepted.text
    fixed_clock.advance(end - fixed_clock())
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    assert fake_x_publisher.published == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("accepted_terms", False),
        ("accepted_terms", None),
        ("approved_specific_clauses", False),
        ("requested_immediate_start", True),
    ],
)
async def test_cardless_acceptance_refuses_missing_false_or_paid_waiver(
    client, coupons, field, value
):
    created = await coupons()
    offer = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    request = confirmation(offer)
    request[field] = value
    assert (await client.post(REDEEM, json=request)).status_code == 422
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0


async def test_midnight_preview_requires_review_without_shortening_months(
    client, coupons, fixed_clock
):
    fixed_clock.advance(datetime(2028, 1, 31, 23, 59, tzinfo=timezone.utc) - fixed_clock())
    created = await coupons()
    offer = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    fixed_clock.advance(timedelta(minutes=2))
    assert (await client.post(REDEEM, json=confirmation(offer))).status_code == 409
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 0
    fresh = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    result = (await client.post(REDEEM, json=confirmation(fresh))).json()
    assert result["starts_at"] == "2028-02-01T00:01:00Z"
    assert result["ends_at"] == "2028-05-01T00:01:00Z"


async def test_completed_operation_replays_after_disable_and_feature_off(
    client, coupons, monkeypatch
):

    created = await coupons()
    offer = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    request = confirmation(offer)
    result = await client.post(REDEEM, json=request)
    await coupons(created["id"], command="disable")
    monkeypatch.setattr(settings, "COUPONS_ENABLED", False)
    assert (await client.post(REDEEM, json=request)).json() == result.json()


async def test_new_paid_checkout_is_refused_during_free_time(
    client, coupons, fake_billing, fixed_clock
):

    created = await coupons()
    offer = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await client.post(REDEEM, json=confirmation(offer))).status_code == 200
    response = await client.post(
        "/api/v1/billing/checkout",
        json={
            "plan_key": "pumpkit_pro_monthly",
            "terms_version": TERMS_VERSION,
            "accepted_terms": True,
            "requested_immediate_start": True,
            "approved_specific_clauses": True,
        },
    )
    assert response.status_code == 409
    assert fake_billing.checkouts == []


async def test_rotation_retains_old_claim_matching_and_missing_keys_fail_closed(
    client, coupons, monkeypatch, fixed_clock
):

    created = await coupons("--max-redemptions", "5")
    offer = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await client.post(REDEEM, json=confirmation(offer))).status_code == 200
    fixed_clock.advance(timedelta(days=100))
    ring = json.loads(KEYS)
    ring["keys"]["v2"] = "MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE="
    ring["active"] = "v2"
    monkeypatch.setattr(settings, "COUPON_IDENTITY_KEYS", SecretStr(json.dumps(ring)))
    assert (await client.post(PREVIEW, json={"code": created["code"]})).status_code == 409
    del ring["keys"]["v1"]
    monkeypatch.setattr(settings, "COUPON_IDENTITY_KEYS", SecretStr(json.dumps(ring)))
    assert (await client.post(PREVIEW, json={"code": created["code"]})).status_code == 503
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 1


async def test_deletion_queues_file_cleanup_and_retry_removes_the_last_accounts_files(
    authed_client,
    coupons,
    user,
    db_session_maker,
    fake_billing,
    file_storage,
    post_with,
    connect_x,
    monkeypatch,
):
    created = await coupons()
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).status_code == 200
    await connect_x()
    post_id = await post_with("Private account media")
    attached = await authed_client.post(
        f"/api/v1/posts/{post_id}/text/parts/1/media",
        files={"file": ("image.png", png(), "image/png")},
    )
    assert attached.status_code == 201, attached.text
    assert len(await file_storage.list_files("media")) == 2
    original_delete = file_storage.delete

    async def unavailable(key):
        raise OSError("Storage unavailable")

    monkeypatch.setattr(file_storage, "delete", unavailable)
    err = StringIO()
    status = await run_cli(
        ["--user-id", user.id],
        sessions=db_session_maker,
        gateway=fake_billing,
        storage=file_storage,
        stdout=StringIO(),
        stderr=err,
    )
    assert status == 1
    assert "queued files remain pending" in err.getvalue()
    assert (await authed_client.get("/api/v1/billing/me")).status_code == 401
    monkeypatch.setattr(file_storage, "delete", original_delete)
    status = await run_cli(
        ["--retry-files"],
        sessions=db_session_maker,
        gateway=fake_billing,
        storage=file_storage,
        stdout=StringIO(),
        stderr=StringIO(),
    )
    assert status == 0
    assert await file_storage.list_files("media") == []


async def test_cardless_writing_spends_the_full_monthly_allowance_and_resets(
    client, coupons, fixed_clock, fake_x_reader, fake_llm
):
    created = await coupons("--months", "2")
    offer = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await client.post(REDEEM, json=confirmation(offer))).status_code == 200
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="coupon-author-post", text="A useful writing example", posted_at=fixed_clock()
        )
    ]
    assert (
        await client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    ).status_code == 201
    fake_llm.replies = [written("Sketch"), {"post": "Written during free access"}]
    response = await client.post("/api/v1/posts", json={"brief": "Write a useful note"})
    assert response.status_code == 201, response.text
    usage = (await client.get("/api/v1/usage")).json()["allowance"]
    assert usage["generations"]["limit"] == 500
    assert usage["generations"]["used"] == 1
    fixed_clock.advance(timedelta(days=31))
    assert (await client.get("/api/v1/usage")).json()["allowance"]["generations"]["used"] == 0


async def test_publisher_rechecks_access_before_a_later_thread_part(
    client,
    coupons,
    fixed_clock,
    connect_x,
    post_with,
    db_session_maker,
    fake_x_publisher,
    file_storage,
):
    fixed_clock.advance(timedelta(seconds=-30))
    created = await coupons("--months", "1")
    offer = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    result = (await client.post(REDEEM, json=confirmation(offer))).json()
    end = datetime.fromisoformat(result["ends_at"].replace("Z", "+00:00"))
    await connect_x()
    post_id = await post_with("First part", "Second part")
    response = await client.post(
        "/api/v1/scheduled-posts",
        json={"post_id": post_id, "publish_at": (end - timedelta(minutes=1)).isoformat()},
    )
    assert response.status_code == 201, response.text
    fixed_clock.advance(end - timedelta(minutes=1) - fixed_clock())

    async def reaches_expiry():
        fixed_clock.advance(end - fixed_clock())

    fake_x_publisher.while_publishing = reaches_expiry
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    assert len(fake_x_publisher.published) == 1


async def test_operation_lookup_and_identifier_uniqueness_are_caller_scoped(
    authed_client, coupons, new_browser, sign_in_by_magic_link
):
    created = await coupons("--max-redemptions", "2")
    offer = (await authed_client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await authed_client.post(REDEEM, json=confirmation(offer))).status_code == 200
    other = new_browser()
    signed = await sign_in_by_magic_link(other, "another-recipient@example.com")
    other.headers["Authorization"] = "Bearer " + signed.access_token
    assert (await other.get(REDEEM + "/redeem-test-0001")).status_code == 404
    assert (await other.post(REDEEM, json=confirmation(offer))).status_code == 409
    other_offer = (await other.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await other.post(REDEEM, json=confirmation(other_offer))).status_code == 200
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 2


async def test_deletion_waits_for_an_in_flight_x_publish_to_settle(
    client,
    coupons,
    fixed_clock,
    connect_x,
    post_with,
    db_session_maker,
    fake_x_publisher,
    fake_billing,
    file_storage,
    user,
):
    fixed_clock.advance(timedelta(seconds=-30))
    created = await coupons()
    offer = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await client.post(REDEEM, json=confirmation(offer))).status_code == 200
    await connect_x()
    post_id = await post_with("Accepted by X while support requests deletion")
    at = fixed_clock() + timedelta(minutes=1)
    response = await client.post(
        "/api/v1/scheduled-posts", json={"post_id": post_id, "publish_at": at.isoformat()}
    )
    assert response.status_code == 201
    entered, release = asyncio.Event(), asyncio.Event()

    async def held_x_call():
        entered.set()
        await release.wait()

    fake_x_publisher.while_publishing = held_x_call
    fixed_clock.advance(timedelta(minutes=1))
    task = asyncio.create_task(
        run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        error = StringIO()
        status = await run_cli(
            ["--user-id", user.id],
            sessions=db_session_maker,
            gateway=fake_billing,
            storage=file_storage,
            stdout=StringIO(),
            stderr=error,
        )
        assert status == 1
        assert "publishing" in error.getvalue()
    finally:
        release.set()
        await asyncio.wait_for(task, 5)
    post = (await client.get(f"/api/v1/posts/{post_id}")).json()
    assert post["scheduled_post"]["state"] == "published"
    assert (
        post["scheduled_post"]["parts"][0]["x_post_url"]
        == "https://x.com/i/web/status/1890000000000000001"
    )
    assert (
        await run_cli(
            ["--user-id", user.id],
            sessions=db_session_maker,
            gateway=fake_billing,
            storage=file_storage,
            stdout=StringIO(),
            stderr=StringIO(),
        )
        == 0
    )


async def test_publisher_rechecks_free_access_after_a_token_refresh_crosses_expiry(
    client,
    coupons,
    fixed_clock,
    connect_x,
    post_with,
    db_session_maker,
    fake_x_publisher,
    file_storage,
    monkeypatch,
):
    fixed_clock.advance(timedelta(seconds=-30))
    created = await coupons("--months", "1")
    offer = (await client.post(PREVIEW, json={"code": created["code"]})).json()
    result = (await client.post(REDEEM, json=confirmation(offer))).json()
    end = datetime.fromisoformat(result["ends_at"].replace("Z", "+00:00"))
    await connect_x()
    post_id = await post_with("Accepted before expiry", "Must not start after a slow refresh")
    at = end - timedelta(hours=2)
    response = await client.post(
        "/api/v1/scheduled-posts", json={"post_id": post_id, "publish_at": at.isoformat()}
    )
    assert response.status_code == 201
    fixed_clock.advance(at - fixed_clock())
    original_refresh = fake_x_publisher.refresh

    async def slow_refresh(*, refresh_token, now):
        tokens = await original_refresh(refresh_token=refresh_token, now=now)
        if len(fake_x_publisher.refreshes) == 2:
            fixed_clock.advance(end - fixed_clock())
        return tokens

    async def first_part_took_time():
        fixed_clock.advance(end - timedelta(minutes=4) - fixed_clock())

    monkeypatch.setattr(fake_x_publisher, "refresh", slow_refresh)
    fake_x_publisher.while_publishing = first_part_took_time
    await run_pass(db_session_maker, fake_x_publisher, file_storage, fixed_clock)
    assert len(fake_x_publisher.refreshes) == 2
    assert len(fake_x_publisher.published) == 1
