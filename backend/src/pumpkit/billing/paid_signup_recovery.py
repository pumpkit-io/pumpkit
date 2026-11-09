import argparse
import asyncio
import sys
from typing import Optional, Sequence, TextIO

import pumpkit.models  # noqa: F401
from pumpkit.auth.service import users
from pumpkit.billing import mediator, paid_signups
from pumpkit.billing.gateway import BillingGateway, get_billing_gateway
from pumpkit.core.db.session import _db_session_handler
from pumpkit.core.time import Clock, system_clock


async def run_cli(
    argv: Sequence[str],
    *,
    sessions=_db_session_handler.async_session_maker,
    gateway: Optional[BillingGateway] = None,
    clock: Clock = system_clock,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    parser = argparse.ArgumentParser(
        description="Recover explicit future paid signups without changing accepted dates."
    )
    parser.add_argument("command", choices=["recover"])
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--operation-id")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    if args.limit < 1 or args.limit > 1000:
        parser.error("--limit must be between 1 and 1000")
    billing_gateway = gateway or get_billing_gateway()
    async with sessions() as db:
        candidates = [(op.user_id, op.operation_id) for op in await paid_signups.pending(db)]
    unresolved = False
    for user_id, operation_id in [
        p for p in candidates if not args.operation_id or p[1] == args.operation_id
    ][: args.limit]:
        if args.list:
            print(f"{operation_id}: pending", file=stdout)
            continue
        try:
            async with sessions() as db:
                user = await users.get_user_by_id(db, user_id)
                if user is None:
                    continue
                result = await mediator.lookup_paid_signup(
                    db, billing_gateway, user, operation_id=operation_id, clock=clock
                )
                unresolved = unresolved or result.status == "pending"
                print(f"{operation_id}: {result.status}", file=stdout)
        except Exception:
            unresolved = True
            print(f"{operation_id}: recovery unavailable; retry or contact support", file=stderr)
    return 1 if unresolved else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_cli(sys.argv[1:])))
