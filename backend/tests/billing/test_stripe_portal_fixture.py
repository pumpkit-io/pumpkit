import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import stripe

FIXTURE = Path(__file__).with_name("stripe_portal_fixture.py")


def load_fixture(optimization: int) -> dict[str, Any]:
    namespace: dict[str, Any] = {"__name__": "portal_fixture_guard_test"}
    exec(compile(FIXTURE.read_text(), str(FIXTURE), "exec", optimize=optimization), namespace)
    return namespace


@pytest.mark.parametrize("optimization", [0, 1, 2])
def test_live_key_is_refused_before_provider_access_or_ledger_creation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, optimization: int
):
    ledger = tmp_path / "resources.json"
    monkeypatch.setenv("PUMPKIT_STRIPE_TEST_KEY", "sk_live_forbidden")
    monkeypatch.setattr(sys, "argv", [str(FIXTURE), "create", "--ledger", str(ledger)])

    def forbidden_client(*args: Any, **kwargs: Any):
        pytest.fail("A live key reached the provider client")

    monkeypatch.setattr(stripe, "StripeClient", forbidden_client)
    with pytest.raises(ValueError, match="test credential"):
        load_fixture(optimization)["main"]()
    assert not ledger.exists()


@pytest.mark.parametrize("optimization", [0, 1, 2])
def test_provider_live_mode_is_refused_before_resource_creation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, optimization: int
):
    ledger = tmp_path / "resources.json"
    monkeypatch.setenv("PUMPKIT_STRIPE_TEST_KEY", "sk_test_guard_fixture")
    monkeypatch.setattr(sys, "argv", [str(FIXTURE), "create", "--ledger", str(ledger)])
    balance_reads = []

    def balance():
        balance_reads.append(True)
        return SimpleNamespace(livemode=True)

    client = SimpleNamespace(v1=SimpleNamespace(balance=SimpleNamespace(retrieve=balance)))
    monkeypatch.setattr(stripe, "StripeClient", lambda *args, **kwargs: client)
    with pytest.raises(ValueError, match="test mode"):
        load_fixture(optimization)["main"]()
    assert balance_reads == [True]
    assert not ledger.exists()


@pytest.mark.parametrize("optimization", [0, 1, 2])
def test_failed_cleanup_keeps_recovery_state_and_never_reports_success(
    tmp_path: Path, optimization: int
):
    ledger = tmp_path / "resources.json"
    ledger.write_text(json.dumps({"configs": ["bpc_owned"], "clocks": [], "prices": []}))

    def unavailable(configuration: str):
        raise stripe.APIConnectionError("Owned configuration unavailable")

    client = SimpleNamespace(
        v1=SimpleNamespace(
            billing_portal=SimpleNamespace(configurations=SimpleNamespace(retrieve=unavailable))
        )
    )
    with pytest.raises(ValueError, match="cleanup"):
        load_fixture(optimization)["execute"](
            client, SimpleNamespace(command="cleanup", ledger=ledger)
        )
    assert json.loads(ledger.read_text())["configs"] == ["bpc_owned"]
