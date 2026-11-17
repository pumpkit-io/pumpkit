"""Redacted configuration readback for installed billing processes."""

import argparse
import json
import sys
from typing import Sequence, TextIO

try:
    from pumpkit.core.config import Settings, settings
except (ValueError, OSError):
    raise SystemExit("Billing configuration is invalid; check the protected environment.") from None


def run_cli(
    argv: Sequence[str],
    *,
    configuration: Settings = settings,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    configured = configuration.is_stripe_billing_configured()
    print(
        json.dumps(
            {
                "schema_version": 1,
                "purchase_pause": {
                    "contract_version": 1,
                    "supported_paths": ["subscription", "top_up", "arranged_paid_signup"],
                    "paused": configuration.BILLING_PURCHASES_PAUSED,
                },
                "billing_configured": configured,
                "top_up_configured": configured and bool(configuration.BILLING_TOP_UP_KEY),
                "managed_payments": configuration.STRIPE_MANAGED_PAYMENTS,
            }
        ),
        file=stdout,
    )
    if not configured:
        print("Stripe billing is not configured.", file=stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(sys.argv[1:]))
