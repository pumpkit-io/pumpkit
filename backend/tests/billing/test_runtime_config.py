import json
import subprocess
import sys
from datetime import datetime, timezone
from io import StringIO

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pumpkit.auth.models import User
from pumpkit.billing.runtime_config import run_cli
from tests.core.test_config import _STRIPE_ENV
from tests.core.test_config import instance_env as instance_env


async def test_operational_readback_distinguishes_complete_capability_from_effective_pause(
    instance_env,
):
    configuration = instance_env(**_STRIPE_ENV, BILLING_PURCHASES_PAUSED="true")
    out = StringIO()
    assert await run_cli([], configuration=configuration, stdout=out) == 0
    assert json.loads(out.getvalue()) == {
        "schema_version": 1,
        "purchase_pause": {
            "contract_version": 2,
            "supported_paths": ["subscription", "top_up", "arranged_paid_signup"],
            "paused": True,
        },
        "verification_user": {"selected": False, "valid": True, "fingerprint": None},
        "billing_configured": True,
        "top_up_configured": False,
        "managed_payments": False,
    }
    configuration = instance_env(
        **_STRIPE_ENV,
        BILLING_PURCHASES_PAUSED="false",
        BILLING_TOP_UP_KEY="top_up",
        STRIPE_MANAGED_PAYMENTS="true",
    )
    out = StringIO()
    assert await run_cli([], configuration=configuration, stdout=out) == 0
    result = json.loads(out.getvalue())
    assert result["purchase_pause"]["paused"] is False
    assert result["top_up_configured"] is True
    assert result["managed_payments"] is True
    assert "sk_test_dummy" not in out.getvalue()


async def test_operational_readback_refuses_missing_billing_without_exposing_configuration(
    instance_env,
):
    out, err = StringIO(), StringIO()
    assert await run_cli([], configuration=instance_env(), stdout=out, stderr=err) == 1
    assert json.loads(out.getvalue())["billing_configured"] is False
    assert err.getvalue() == "Stripe billing is not configured.\n"


def test_operational_entrypoint_redacts_invalid_environment(instance_env, monkeypatch):
    instance_env()
    monkeypatch.setenv("BILLING_PURCHASES_PAUSED", "readback-secret-invalid-boolean")
    result = subprocess.run(
        [sys.executable, "-m", "pumpkit.billing.runtime_config"], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "Billing configuration is invalid; check the protected environment.\n"
    assert "readback-secret" not in result.stderr


@pytest.mark.parametrize("target", ["valid", "missing", "non_x", "suspended"])
async def test_operational_readback_validates_the_existing_x_user_and_redacts_identity(
    instance_env, db, db_session_maker, target
):
    selected_id = "user_01ARZ3NDEKTSV4RRFFQ69G5FAV"
    if target != "missing":
        db.add(
            User(
                id=selected_id,
                email="private-target@example.com",
                display_name="Private target",
                x_user_id=None if target == "non_x" else "424242",
                suspended_until=datetime(2100, 1, 1, tzinfo=timezone.utc)
                if target == "suspended"
                else None,
            )
        )
        await db.commit()
    configuration = instance_env(
        **_STRIPE_ENV, BILLING_PURCHASES_PAUSED="true", BILLING_VERIFICATION_USER_ID=selected_id
    )
    out, err = StringIO(), StringIO()
    status = await run_cli(
        [], configuration=configuration, sessions=db_session_maker, stdout=out, stderr=err
    )
    assert status == (0 if target == "valid" else 1)
    assert json.loads(out.getvalue())["verification_user"] == {
        "selected": True,
        "valid": target == "valid",
        "fingerprint": "dc2ac512fe294a3ce57184aa64f7f2d83dc405a1acdc600d31b065744f856dda",
    }
    assert selected_id not in out.getvalue() + err.getvalue()
    assert "private-target" not in out.getvalue() + err.getvalue()
    assert bool(err.getvalue()) is (target != "valid")


async def test_operational_readback_cannot_confirm_selection_without_a_working_database(
    instance_env, tmp_path
):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'private-database.db'}")
    configuration = instance_env(
        **_STRIPE_ENV,
        BILLING_PURCHASES_PAUSED="true",
        BILLING_VERIFICATION_USER_ID="user_01ARZ3NDEKTSV4RRFFQ69G5FAV",
    )
    out, err = StringIO(), StringIO()
    try:
        status = await run_cli(
            [],
            configuration=configuration,
            sessions=async_sessionmaker(engine),
            stdout=out,
            stderr=err,
        )
    finally:
        await engine.dispose()
    assert status == 1
    assert json.loads(out.getvalue())["verification_user"]["valid"] is False
    assert "private-database" not in out.getvalue() + err.getvalue()
    assert "Traceback" not in err.getvalue()
