import asyncio
import sys

import pumpkit.auth.models  # noqa: F401
from pumpkit.billing.coupons import run_cli
from pumpkit.billing.gateway import get_billing_gateway
from pumpkit.core.config import settings
from pumpkit.core.db.session import _db_session_handler
from pumpkit.core.time import system_clock

if __name__ == "__main__":
    raise SystemExit(
        asyncio.run(
            run_cli(
                sys.argv[1:],
                sessions=_db_session_handler.async_session_maker,
                config=settings,
                gateway=get_billing_gateway(),
                clock=system_clock,
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
        )
    )
