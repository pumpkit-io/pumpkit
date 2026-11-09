import argparse
import json
from collections.abc import Sequence
from typing import NoReturn, TextIO

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pumpkit.billing import coupon_service
from pumpkit.billing.gateway import BillingGateway, BillingProviderError
from pumpkit.billing.schemas import CouponIssueRequest
from pumpkit.core.config import Settings
from pumpkit.core.time import Clock


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise coupon_service.CouponCommandError(
            "Invalid command arguments. Use --help for options."
        )


async def run_cli(
    argv: Sequence[str],
    *,
    sessions: async_sessionmaker[AsyncSession],
    config: Settings,
    gateway: BillingGateway,
    clock: Clock,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    parser = _Parser(prog="python -m pumpkit.billing.coupons")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--months", type=int, required=True)
    create.add_argument("--max-redemptions", type=int, default=1)
    create.add_argument("--recipient")
    create.add_argument("--claim-deadline")
    inspect = commands.add_parser("inspect")
    inspect.add_argument("id")
    disable = commands.add_parser("disable")
    disable.add_argument("id")
    commands.add_parser("list")
    commands.add_parser("purge")
    try:
        args = parser.parse_args(argv)
        if args.command == "create":
            coupon_service.require_enabled(config)
            coupon_service.validate_offers(
                await gateway.list_plans(config.BILLING_PLAN_KEYS), config=config
            )
        result: object
        async with sessions() as db:
            if args.command == "create":
                request = CouponIssueRequest(
                    months=args.months,
                    max_redemptions=args.max_redemptions,
                    recipient=args.recipient,
                    claim_deadline=args.claim_deadline,
                )
                coupon, code = await coupon_service.issue(
                    db, request=request, config=config, now=clock()
                )
                result = {**coupon_service.describe(coupon), "code": code}
            elif args.command == "list":
                result = [
                    coupon_service.describe(coupon)
                    for coupon in await coupon_service.list_coupons(db)
                ]
            elif args.command == "disable":
                result = coupon_service.describe(
                    await coupon_service.disable(db, args.id, now=clock())
                )
            elif args.command == "purge":
                result = {"records_purged": await coupon_service.purge(db, now=clock())}
            else:
                result = coupon_service.describe(await coupon_service.inspect(db, args.id))
            await db.commit()
        print(json.dumps(result), file=stdout)
        return 0
    except coupon_service.CouponCommandError as exc:
        print(str(exc), file=stderr)
        return 1
    except ValidationError:
        print(
            "Invalid coupon inputs: use positive whole months and limit, a valid email, and a UTC deadline.",
            file=stderr,
        )
        return 1
    except BillingProviderError:
        print(
            "Cannot verify configured billing offers. Try again before issuing a coupon.",
            file=stderr,
        )
        return 1
    except SQLAlchemyError:
        print("Coupon command failed; its database transaction was rolled back.", file=stderr)
        return 1
