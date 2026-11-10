import json
from io import BytesIO, StringIO

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from pumpkit.account_deletion import run_cli
from pumpkit.auth.models import User
from pumpkit.billing.models import CouponClaim
from pumpkit.core.config import settings
from pumpkit.core.storage import StoredFileNotFoundError
from pumpkit.posts.models import AccountFileDeletion, Media
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_monthly_coupons import monthly
from tests.billing.test_top_up_account_deletion import remove_user
from tests.billing.test_trial_eligibility import (
    enforce_account_cascades as enforce_account_cascades,
)
from tests.billing.test_trial_eligibility import sign_in
from tests.billing.test_trial_eligibility import sign_in_app as sign_in_app
from tests.billing.test_trial_eligibility import trial_app as trial_app
from tests.billing.test_trial_eligibility import trial_browser as trial_browser
from tests.billing.test_trial_eligibility import trial_keys as trial_keys


async def reset(sessions, gateway, storage, user_id, *, execute=False):
    output, error = StringIO(), StringIO()
    args = ["--user-id", user_id, "--prelaunch-reset"]
    if execute:
        args.append("--execute")
    result = await run_cli(
        args,
        sessions=sessions,
        gateway=gateway,
        storage=storage,
        stdout=output,
        stderr=error,
    )
    return result, output.getvalue(), error.getvalue()


async def test_prelaunch_reset_previews_without_deleting_or_restoring_benefits(
    trial_browser, fake_x_publisher, coupons, db_session_maker, fake_billing, file_storage
):
    original = await sign_in(trial_browser, fake_x_publisher)
    created = await coupons("--max-redemptions", "5")
    preview = (await trial_browser.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await trial_browser.post(REDEEM, json=confirmation(preview))).status_code == 200

    status, output, error = await reset(
        db_session_maker, fake_billing, file_storage, original["id"]
    )

    assert status == 0, error
    report = json.loads(output)
    assert report["executed"] is False
    assert report["coupon_claims"] == 1
    assert report["trial_eligibility"] == 1
    assert original["id"] not in output
    assert original["email"] not in output
    assert (await trial_browser.get("/api/v1/users/me")).status_code == 200
    assert (await trial_browser.post(PREVIEW, json={"code": created["code"]})).status_code == 409
    assert (await trial_browser.get("/api/v1/billing/me")).json()["trial_days"] is None
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == 1


async def test_prelaunch_execution_resets_only_selected_identity_without_reopening_issuance(
    trial_browser, fake_x_publisher, coupons, db_session_maker, fake_billing, file_storage
):
    original = await sign_in(trial_browser, fake_x_publisher)
    original_auth = trial_browser.headers["Authorization"]
    first = await coupons("--max-redemptions", "5")
    exhausted = await coupons()
    for index, coupon in enumerate((first, exhausted)):
        preview = (await trial_browser.post(PREVIEW, json={"code": coupon["code"]})).json()
        assert (
            await trial_browser.post(
                REDEEM, json=confirmation(preview, f"reset-selected-{index:04d}")
            )
        ).status_code == 200
    other = await sign_in(trial_browser, fake_x_publisher, x_id="2002", email="other@example.org")
    other_coupon = await coupons("--max-redemptions", "5")
    preview = (await trial_browser.post(PREVIEW, json={"code": other_coupon["code"]})).json()
    assert (await trial_browser.post(REDEEM, json=confirmation(preview))).status_code == 200

    status, output, error = await reset(
        db_session_maker, fake_billing, file_storage, original["id"], execute=True
    )

    assert status == 0, error
    assert json.loads(output) == {
        "executed": True,
        "users": 1,
        "coupon_claims": 2,
        "trial_eligibility": 1,
        "files": 0,
    }
    assert (await trial_browser.get("/api/v1/users/me")).json()["id"] == other["id"]
    assert (
        await trial_browser.get("/api/v1/users/me", headers={"Authorization": original_auth})
    ).status_code == 401
    assert (
        await trial_browser.post(PREVIEW, json={"code": other_coupon["code"]})
    ).status_code == 409
    recreated = await sign_in(trial_browser, fake_x_publisher, email="changed@example.org")
    assert recreated["id"] != original["id"]
    assert (await trial_browser.get("/api/v1/billing/me")).json()["trial_days"] == 7
    assert (await trial_browser.post(PREVIEW, json={"code": first["code"]})).status_code == 200
    assert (await trial_browser.post(PREVIEW, json={"code": exhausted["code"]})).status_code == 409
    for coupon in (first, exhausted, other_coupon):
        assert (await coupons(coupon["id"], command="inspect"))["redeemed_count"] == 1


async def test_reset_keeps_known_other_x_claims_when_contact_email_is_shared(
    trial_browser, fake_x_publisher, coupons, db_session_maker, fake_billing, file_storage
):
    original = await sign_in(trial_browser, fake_x_publisher)
    selected_coupon = await coupons("--max-redemptions", "5")
    preview = (await trial_browser.post(PREVIEW, json={"code": selected_coupon["code"]})).json()
    assert (await trial_browser.post(REDEEM, json=confirmation(preview))).status_code == 200
    other = await sign_in(trial_browser, fake_x_publisher, x_id="2002")
    other_coupon = await coupons("--max-redemptions", "5")
    preview = (await trial_browser.post(PREVIEW, json={"code": other_coupon["code"]})).json()
    assert (await trial_browser.post(REDEEM, json=confirmation(preview))).status_code == 200

    status, output, error = await reset(
        db_session_maker, fake_billing, file_storage, original["id"], execute=True
    )

    assert status == 0, error
    assert json.loads(output)["coupon_claims"] == 1
    assert (await trial_browser.get("/api/v1/users/me")).json()["id"] == other["id"]
    assert (
        await trial_browser.post(PREVIEW, json={"code": other_coupon["code"]})
    ).status_code == 409
    assert (await trial_browser.get("/api/v1/billing/me")).json()["trial_days"] is None


@pytest.mark.parametrize("ring", ["COUPON_IDENTITY_KEYS", "TRIAL_IDENTITY_KEYS"])
async def test_reset_requires_historical_identity_keys_before_any_deletion(
    trial_browser,
    fake_x_publisher,
    coupons,
    db_session_maker,
    fake_billing,
    file_storage,
    monkeypatch,
    ring,
):
    original = await sign_in(trial_browser, fake_x_publisher)
    created = await coupons("--max-redemptions", "5")
    preview = (await trial_browser.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await trial_browser.post(REDEEM, json=confirmation(preview))).status_code == 200
    previous = getattr(settings, ring)
    monkeypatch.setattr(
        settings,
        ring,
        SecretStr('{"active":"new","keys":{"new":"MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE="}}'),
    )

    status, output, error = await reset(
        db_session_maker, fake_billing, file_storage, original["id"], execute=True
    )

    assert status == 1
    assert output == ""
    assert "historical" in error
    assert (await trial_browser.get("/api/v1/users/me")).status_code == 200
    monkeypatch.setattr(settings, ring, previous)
    assert (await trial_browser.post(PREVIEW, json={"code": created["code"]})).status_code == 409
    assert (await trial_browser.get("/api/v1/billing/me")).json()["trial_days"] is None


@pytest.mark.parametrize("shared", [False, True])
async def test_reset_refuses_unattributable_email_only_claims(
    trial_browser, fake_x_publisher, coupons, db_session_maker, fake_billing, file_storage, shared
):
    original = await sign_in(trial_browser, fake_x_publisher)
    created = await coupons("--max-redemptions", "5")
    preview = (await trial_browser.post(PREVIEW, json={"code": created["code"]})).json()
    assert (await trial_browser.post(REDEEM, json=confirmation(preview))).status_code == 200
    assert (await remove_user(db_session_maker, fake_billing, file_storage, original["id"]))[0] == 0
    async with db_session_maker() as db:
        claim = await db.scalar(select(CouponClaim))
        assert claim is not None
        claim.x_fingerprint = None
        await db.commit()
    if shared:
        await sign_in(trial_browser, fake_x_publisher, x_id="2002")
    recreated = await sign_in(trial_browser, fake_x_publisher)

    status, output, error = await reset(
        db_session_maker, fake_billing, file_storage, recreated["id"], execute=True
    )

    assert status == 1
    assert output == ""
    assert "attributed" in error
    assert (await trial_browser.get("/api/v1/users/me")).status_code == 200
    assert (await trial_browser.post(PREVIEW, json={"code": created["code"]})).status_code == 409


@pytest.mark.parametrize("execute", [False, True])
async def test_reset_preserves_billing_obligation_guards(
    trial_browser,
    fake_x_publisher,
    db_session_maker,
    fake_billing,
    file_storage,
    fixed_clock,
    execute,
):
    original = await sign_in(trial_browser, fake_x_publisher)
    async with db_session_maker() as db:
        user = await db.get(User, original["id"])
        await monthly(db, user, fake_billing, fixed_clock)

    status, output, error = await reset(
        db_session_maker, fake_billing, file_storage, original["id"], execute=execute
    )

    assert status == 1
    assert output == ""
    assert "obligations" in error
    assert (await trial_browser.get("/api/v1/users/me")).status_code == 200
    assert fake_billing.expired_checkouts == []
    assert fake_billing.cancelled_subscriptions == []


async def test_reset_deletes_only_selected_files_and_leaves_unrelated_cleanup_pending(
    trial_browser,
    fake_x_publisher,
    db_session_maker,
    fake_billing,
    file_storage,
    fixed_clock,
):
    original = await sign_in(trial_browser, fake_x_publisher)
    selected_keys = ("media/selected/file", "media/selected/preview")
    unrelated_key = "media/unrelated/queued"
    for key in (*selected_keys, unrelated_key):
        await file_storage.put(key, BytesIO(b"retained file"))
    async with db_session_maker() as db:
        db.add(
            Media(
                user_id=original["id"],
                kind="image",
                content_type="image/png",
                byte_size=13,
                file_key=selected_keys[0],
                preview_key=selected_keys[1],
                created_at=fixed_clock(),
            )
        )
        db.add(AccountFileDeletion(key=unrelated_key))
        await db.commit()
    assert (await reset(db_session_maker, fake_billing, file_storage, original["id"]))[0] == 0
    assert len(await file_storage.list_files("media")) == 3

    status, output, error = await reset(
        db_session_maker, fake_billing, file_storage, original["id"], execute=True
    )

    assert status == 0, error
    assert json.loads(output)["files"] == 2
    for key in selected_keys:
        with pytest.raises(StoredFileNotFoundError):
            await file_storage.open(key)
    with await file_storage.open(unrelated_key) as stored:
        assert stored.read() == b"retained file"


async def test_committed_reset_file_failure_uses_existing_retry_owner(
    trial_browser,
    fake_x_publisher,
    db_session_maker,
    fake_billing,
    file_storage,
    fixed_clock,
    monkeypatch,
):
    original = await sign_in(trial_browser, fake_x_publisher)
    key = "media/selected/retry"
    await file_storage.put(key, BytesIO(b"retry me"))
    async with db_session_maker() as db:
        db.add(
            Media(
                user_id=original["id"],
                kind="image",
                content_type="image/png",
                byte_size=8,
                file_key=key,
                created_at=fixed_clock(),
            )
        )
        await db.commit()
    delete = file_storage.delete

    async def unavailable(key):
        raise OSError("storage unavailable")

    monkeypatch.setattr(file_storage, "delete", unavailable)
    status, _, error = await reset(
        db_session_maker, fake_billing, file_storage, original["id"], execute=True
    )
    assert status == 1
    assert "--retry-files" in error
    assert (await trial_browser.get("/api/v1/users/me")).status_code == 401
    assert len(await file_storage.list_files("media")) == 1
    monkeypatch.setattr(file_storage, "delete", delete)
    assert (
        await run_cli(
            ["--retry-files"],
            sessions=db_session_maker,
            gateway=fake_billing,
            storage=file_storage,
            stdout=StringIO(),
            stderr=StringIO(),
        )
    ) == 0
    assert await file_storage.list_files("media") == []
