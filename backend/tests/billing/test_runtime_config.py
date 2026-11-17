import json
import subprocess
import sys
from io import StringIO

from pumpkit.billing.runtime_config import run_cli
from tests.core.test_config import _STRIPE_ENV
from tests.core.test_config import instance_env as instance_env


def test_operational_readback_distinguishes_complete_capability_from_effective_pause(instance_env):
    configuration = instance_env(**_STRIPE_ENV, BILLING_PURCHASES_PAUSED="true")
    out = StringIO()
    assert run_cli([], configuration=configuration, stdout=out) == 0
    assert json.loads(out.getvalue()) == {
        "schema_version": 1,
        "purchase_pause": {
            "contract_version": 1,
            "supported_paths": ["subscription", "top_up", "arranged_paid_signup"],
            "paused": True,
        },
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
    assert run_cli([], configuration=configuration, stdout=out) == 0
    result = json.loads(out.getvalue())
    assert result["purchase_pause"]["paused"] is False
    assert result["top_up_configured"] is True
    assert result["managed_payments"] is True
    assert "sk_test_dummy" not in out.getvalue()


def test_operational_readback_refuses_missing_billing_without_exposing_configuration(instance_env):
    out, err = StringIO(), StringIO()
    assert run_cli([], configuration=instance_env(), stdout=out, stderr=err) == 1
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
