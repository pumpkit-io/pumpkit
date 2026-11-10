import asyncio
import json
from io import BytesIO, StringIO

import pytest
from sqlalchemy import select

from pumpkit.account_deletion import run_cli
from pumpkit.auth.models import User
from pumpkit.posts.models import AccountFileDeletion, Media
from tests.billing.postgres.test_coupon_contention import wait_for_locks
from tests.billing.test_coupon_preview import coupons as coupons
from tests.billing.test_coupon_redemption import PREVIEW, REDEEM, confirmation
from tests.billing.test_prelaunch_reset import reset
from tests.billing.test_prelaunch_reset import (
    test_committed_reset_file_failure_uses_existing_retry_owner as test_committed_reset_file_failure_uses_existing_retry_owner,
)
from tests.billing.test_prelaunch_reset import (
    test_prelaunch_execution_resets_only_selected_identity_without_reopening_issuance as test_prelaunch_execution_resets_only_selected_identity_without_reopening_issuance,
)
from tests.billing.test_prelaunch_reset import (
    test_prelaunch_reset_previews_without_deleting_or_restoring_benefits as test_prelaunch_reset_previews_without_deleting_or_restoring_benefits,
)
from tests.billing.test_prelaunch_reset import (
    test_reset_deletes_only_selected_files_and_leaves_unrelated_cleanup_pending as test_reset_deletes_only_selected_files_and_leaves_unrelated_cleanup_pending,
)
from tests.billing.test_prelaunch_reset import (
    test_reset_keeps_known_other_x_claims_when_contact_email_is_shared as test_reset_keeps_known_other_x_claims_when_contact_email_is_shared,
)
from tests.billing.test_prelaunch_reset import (
    test_reset_preserves_billing_obligation_guards as test_reset_preserves_billing_obligation_guards,
)
from tests.billing.test_prelaunch_reset import (
    test_reset_refuses_unattributable_email_only_claims as test_reset_refuses_unattributable_email_only_claims,
)
from tests.billing.test_prelaunch_reset import (
    test_reset_requires_historical_identity_keys_before_any_deletion as test_reset_requires_historical_identity_keys_before_any_deletion,
)
from tests.billing.test_trial_eligibility import sign_in
from tests.billing.test_trial_eligibility import sign_in_app as sign_in_app
from tests.billing.test_trial_eligibility import trial_app as trial_app
from tests.billing.test_trial_eligibility import trial_browser as trial_browser
from tests.billing.test_trial_eligibility import trial_keys as trial_keys

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("reset_first", [False, True])
async def test_reset_and_claim_serialize_without_granting_after_deletion(
    trial_browser,
    fake_x_publisher,
    coupons,
    db_session_maker,
    db_engine,
    fake_billing,
    file_storage,
    reset_first,
):
    original = await sign_in(trial_browser, fake_x_publisher)
    created = await coupons("--max-redemptions", "5")
    offer = (await trial_browser.post(PREVIEW, json={"code": created["code"]})).json()
    async with db_session_maker() as control:
        await control.scalar(select(User).where(User.id == original["id"]).with_for_update())
        requests = [
            lambda: reset(
                db_session_maker, fake_billing, file_storage, original["id"], execute=True
            ),
            lambda: trial_browser.post(REDEEM, json=confirmation(offer)),
        ]
        if not reset_first:
            requests.reverse()
        tasks = [asyncio.create_task(requests[0]())]
        try:
            await wait_for_locks(db_engine, 1)
            tasks.append(asyncio.create_task(requests[1]()))
            await wait_for_locks(db_engine, 2)
        finally:
            await control.commit()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 10)
    (status, output, error), response = results if reset_first else results[::-1]
    assert status == 0, error
    assert response.status_code == (403 if reset_first else 200)
    assert json.loads(output)["coupon_claims"] == (0 if reset_first else 1)
    await sign_in(trial_browser, fake_x_publisher, email="changed@example.org")
    assert (await trial_browser.get("/api/v1/billing/me")).json()["trial_days"] == 7
    assert (await trial_browser.post(PREVIEW, json={"code": created["code"]})).status_code == 200
    assert (await coupons(created["id"], command="inspect"))["redeemed_count"] == (
        0 if reset_first else 1
    )


async def test_reset_does_not_report_success_while_selected_cleanup_is_locked(
    trial_browser,
    fake_x_publisher,
    db_session_maker,
    fake_billing,
    file_storage,
    fixed_clock,
):
    original = await sign_in(trial_browser, fake_x_publisher)
    key = "media/selected/held"
    await file_storage.put(key, BytesIO(b"pending cleanup"))
    async with db_session_maker() as db:
        db.add(
            Media(
                user_id=original["id"],
                kind="image",
                content_type="image/png",
                byte_size=15,
                file_key=key,
                created_at=fixed_clock(),
            )
        )
        db.add(AccountFileDeletion(key=key))
        await db.commit()
    async with db_session_maker() as control:
        await control.scalar(
            select(AccountFileDeletion).where(AccountFileDeletion.key == key).with_for_update()
        )
        try:
            status, output, error = await asyncio.wait_for(
                reset(db_session_maker, fake_billing, file_storage, original["id"], execute=True),
                10,
            )
        finally:
            await control.commit()
    assert status == 1
    assert output == ""
    assert "cleanup is still pending" in error
    assert (await trial_browser.get("/api/v1/users/me")).status_code == 401
    with await file_storage.open(key) as stored:
        assert stored.read() == b"pending cleanup"
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
