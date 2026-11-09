import json
import os
import subprocess
import sys
from datetime import timedelta
from io import StringIO

import pytest

from pumpkit.billing import coupon_service
from pumpkit.billing.coupons import run_cli
from pumpkit.billing.gateway import Plan
from pumpkit.core.config import Settings, settings

KEYS = '{"active":"v1","keys":{"v1":"MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="}}'


@pytest.fixture
def coupon_config():
    return Settings(
        **{**settings.model_dump(), "COUPONS_ENABLED": True, "COUPON_IDENTITY_KEYS": KEYS}
    )


@pytest.fixture
def commands(db_session_maker, coupon_config, fake_billing, fixed_clock):
    fake_billing.plans = [
        Plan("pumpkit_pro_monthly", "price_monthly", "Pro", 2000, "eur", "month", 1)
    ]

    async def run(*args, config=None):
        out, err = StringIO(), StringIO()
        result = await run_cli(
            list(args),
            sessions=db_session_maker,
            config=config or coupon_config,
            gateway=fake_billing,
            clock=fixed_clock,
            stdout=out,
            stderr=err,
        )
        return result, json.loads(out.getvalue()) if out.getvalue() else None, err.getvalue()

    return run


async def test_create_delivers_a_code_once_and_inspection_cannot_recover_it(commands, db):
    status, created, error = await commands("create", "--months", "3")
    assert (status, error) == (0, "")
    assert len(created["code"]) >= 22
    coupon = await coupon_service.find_by_code(db, created["code"])
    assert coupon is not None and coupon.id == created["id"]
    status, inspected, error = await commands("inspect", created["id"])
    assert (status, error) == (0, "")
    assert inspected["months"] == 3
    assert inspected["max_redemptions"] == 1
    assert inspected["recipient_restricted"] is False
    assert "code" not in inspected
    assert created["code"] not in json.dumps(inspected)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--months", "0"],
        ["--months", "-1"],
        ["--months", "1.5"],
        ["--months", "2", "--recipient", "not-an-email"],
        ["--months", "2", "--claim-deadline", "2020-01-01T00:00:00Z"],
        ["--months", "2", "--claim-deadline", "2030-01-01T00:00:00"],
        ["--months", "2", "--max-redemptions", "0"],
    ],
)
async def test_invalid_issuance_is_refused_without_echoing_recipient(commands, arguments):
    status, result, error = await commands("create", *arguments)
    assert status == 1
    assert result is None
    assert error
    assert "not-an-email" not in error


async def test_reserved_recipient_matches_normalized_email_after_key_rotation(
    commands, db, coupon_config, caplog
):
    _, created, _ = await commands(
        "create", "--months", "2", "--recipient", " Recipient@Example.COM "
    )
    coupon = await coupon_service.find_by_code(db, created["code"])
    assert coupon is not None
    rotated = Settings(
        **{
            **coupon_config.model_dump(),
            "COUPON_IDENTITY_KEYS": '{"active":"v2","keys":{"v1":"MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=","v2":"MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE="}}',
        }
    )
    assert coupon_service.matches_recipient(coupon, "recipient@example.com", config=rotated)
    assert not coupon_service.matches_recipient(coupon, "someone@example.com", config=rotated)
    _, inspected, _ = await commands("inspect", created["id"])
    assert inspected["recipient_restricted"] is True
    assert "recipient@example.com" not in json.dumps(inspected).lower()
    assert created["code"] not in caplog.text
    assert "recipient@example.com" not in caplog.text.lower()


async def test_disable_is_idempotent_and_purge_keeps_claimable_assignments(
    commands, fixed_clock, coupon_config, db
):
    _, issued, _ = await commands("create", "--months", "1", "--recipient", "recipient@example.com")
    _, still_claimable, _ = await commands(
        "create", "--months", "1", "--recipient", "other@example.com"
    )
    _, first_disable, _ = await commands("disable", issued["id"])
    fixed_clock.advance(timedelta(days=1))
    _, second_disable, _ = await commands("disable", issued["id"])
    assert first_disable["disabled_at"] == second_disable["disabled_at"]
    _, listed, _ = await commands("list")
    assert {item["id"] for item in listed} == {issued["id"], still_claimable["id"]}
    disabled_config = Settings(**{**coupon_config.model_dump(), "COUPONS_ENABLED": False})
    _, before, _ = await commands("purge", config=disabled_config)
    assert before == {"records_purged": 0}
    fixed_clock.advance(timedelta(days=29))
    status, purged, error = await commands("purge", config=disabled_config)
    assert (status, error) == (0, "")
    assert purged == {"records_purged": 1}
    _, inspected, _ = await commands("inspect", issued["id"])
    assert inspected["recipient_restricted"] is True
    assert inspected["recipient_retained"] is False
    _, retained, _ = await commands("inspect", still_claimable["id"])
    assert retained["recipient_retained"] is True


@pytest.mark.parametrize("billing_disabled", [False, True])
async def test_creation_off_or_without_plans_has_no_record_or_provider_call(
    commands, coupon_config, fake_billing, billing_disabled
):
    overrides = (
        {"COUPONS_ENABLED": False}
        if not billing_disabled
        else {
            "BILLING_PLAN_KEYS": [],
            "STRIPE_SECRET_KEY": None,
            "STRIPE_PUBLISHABLE_KEY": None,
            "STRIPE_WEBHOOK_SECRET": None,
        }
    )
    config = Settings(**{**coupon_config.model_dump(), **overrides})
    status, result, error = await commands("create", "--months", "2", config=config)
    assert status == 1 and result is None
    assert "configured plans" in error
    _, listed, _ = await commands("list")
    assert listed == []
    assert fake_billing.plan_lookups == []


@pytest.mark.parametrize(
    "plans",
    [
        [],
        [Plan("pumpkit_pro_monthly", "price_monthly", "Pro", 2000, "eur", "week", 1)],
        [Plan("pumpkit_pro_monthly", "price_monthly", "Pro", 2000, "eur", "month", 2)],
    ],
)
async def test_issuance_refuses_incompatible_configured_offers_without_writing(
    commands, fake_billing, plans
):
    fake_billing.plans = plans
    status, result, error = await commands("create", "--months", "2")
    assert status == 1 and result is None
    assert "compatible" in error
    _, listed, _ = await commands("list")
    assert listed == []


def test_module_help_runs_without_database_access():
    result = subprocess.run(
        [sys.executable, "-m", "pumpkit.billing.coupons", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "create" in result.stdout and "purge" in result.stdout


def test_invalid_key_configuration_never_echoes_secret_in_startup_errors():
    secret = "SECRET-KEY-MATERIAL-NOT-BASE64"
    result = subprocess.run(
        [sys.executable, "-m", "pumpkit.billing.coupons", "list"],
        env={
            **os.environ,
            "COUPONS_ENABLED": "true",
            "COUPON_IDENTITY_KEYS": '{"active":"v1","keys":{"v1":"' + secret + '"}}',
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "COUPON_IDENTITY_KEYS" in result.stderr
    assert secret not in result.stderr + result.stdout


async def test_deadline_purge_uses_deadline_instant_and_missing_old_keys_fail_closed(
    commands, db, coupon_config, fixed_clock
):
    deadline = fixed_clock() + timedelta(days=1)
    _, created, _ = await commands(
        "create",
        "--months",
        "1",
        "--recipient",
        "recipient@example.com",
        "--claim-deadline",
        deadline.isoformat(),
    )
    coupon = await coupon_service.find_by_code(db, created["code"])
    assert coupon is not None
    missing_old = Settings(
        **{
            **coupon_config.model_dump(),
            "COUPON_IDENTITY_KEYS": '{"active":"v2","keys":{"v2":"MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE="}}',
        }
    )
    with pytest.raises(coupon_service.CouponCommandError, match="required coupon identity key"):
        coupon_service.matches_recipient(coupon, "recipient@example.com", config=missing_old)
    fixed_clock.advance(timedelta(days=30, hours=23, minutes=59, seconds=59))
    _, pending, _ = await commands("purge")
    assert pending == {"records_purged": 0}
    fixed_clock.advance(timedelta(seconds=1))
    _, purged, _ = await commands("purge")
    assert purged == {"records_purged": 1}


async def test_provider_catalog_failure_has_no_code_or_record(commands, fake_billing):
    fake_billing.fail_on = {"list_plans"}
    status, result, error = await commands("create", "--months", "2")
    assert status == 1 and result is None
    assert "Cannot verify" in error
    _, listed, _ = await commands("list")
    assert listed == []


async def test_purge_records_deadline_terminal_time_even_for_general_codes(commands, fixed_clock):
    deadline = fixed_clock() + timedelta(days=1)
    _, created, _ = await commands(
        "create", "--months", "1", "--claim-deadline", deadline.isoformat()
    )
    fixed_clock.advance(timedelta(days=1))
    _, purged, _ = await commands("purge")
    assert purged == {"records_purged": 0}
    _, inspected, _ = await commands("inspect", created["id"])
    assert inspected["unclaimable_at"] == deadline.isoformat()
