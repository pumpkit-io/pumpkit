"""Redacted configuration readback for installed billing processes."""

import argparse
import asyncio
import hashlib
import json
import sys
from typing import Sequence, TextIO

from sqlalchemy.exc import SQLAlchemyError

try:
    from pumpkit.core.config import Settings, settings
except (ValueError, OSError):
    raise SystemExit("Billing configuration is invalid; check the protected environment.") from None

from pumpkit.auth.service import sessions as auth_sessions
from pumpkit.auth.service import users
from pumpkit.core.db.session import _db_session_handler


async def run_cli(
    argv: Sequence[str],
    *,
    configuration: Settings = settings,
    sessions=_db_session_handler.async_session_maker,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    configured = configuration.is_stripe_billing_configured()
    selected = configuration.BILLING_VERIFICATION_USER_ID
    valid = True
    if selected:
        try:
            async with sessions() as db:
                user = await users.get_user_by_id(db, selected)
                valid = (
                    user is not None
                    and user.x_user_id is not None
                    and auth_sessions.may_hold_session(user)
                )
        except (SQLAlchemyError, OSError, TimeoutError):
            valid = False
    print(
        json.dumps(
            {
                "schema_version": 1,
                "purchase_pause": {
                    "contract_version": 2,
                    "supported_paths": ["subscription", "top_up", "arranged_paid_signup"],
                    "paused": configuration.BILLING_PURCHASES_PAUSED,
                },
                "verification_user": {
                    "selected": selected is not None,
                    "valid": valid,
                    "fingerprint": hashlib.sha256(
                        ("pumpkit:billing-verification-user:v1:" + selected).encode()
                    ).hexdigest()
                    if selected
                    else None,
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
    if not valid:
        print("The verification user could not be validated; purchases remain paused.", file=stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_cli(sys.argv[1:])))
