import argparse
import json
from collections.abc import Sequence
from typing import NoReturn, TextIO

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pumpkit.auth.service import users
from pumpkit.billing import coupon_operations, coupon_service, mediator
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
    recover = commands.add_parser("recover")
    recover.add_argument("--operation-id")
    recover.add_argument("--limit", type=int, default=100)
    recover.add_argument("--list", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.command == "recover":
            if not 1 <= args.limit <= 1000:
                raise coupon_service.CouponCommandError("Use a recovery limit between 1 and 1000.")
            async with sessions() as db:
                candidates = await coupon_operations.recovery_candidates(
                    db, operation_id=args.operation_id, limit=args.limit
                )
            outcomes = []
            for user_id, operation_id in candidates:
                async with sessions() as db:
                    operation = await coupon_operations.find(
                        db, user_id=user_id, operation_id=operation_id
                    )
                    assert operation is not None
                    item = {
                        "id": operation.id,
                        "status": operation.status,
                        "created_at": operation.created_at.isoformat(),
                        "attempts": operation.attempts,
                    }
                    if not args.list:
                        user = await users.get_user_by_id(db, user_id)
                        if user is None:
                            item["status"] = "conflict"
                        else:
                            try:
                                resolved = await mediator.lookup_coupon_redemption(
                                    db, gateway, user, operation_id=operation_id, clock=clock
                                )
                                item["status"] = resolved.status
                            except Exception:
                                await db.rollback()
                                item["status"] = "pending"
                    outcomes.append(item)
            print(
                json.dumps(
                    {
                        "operations": outcomes,
                        "remaining": sum(item["status"] == "pending" for item in outcomes),
                    }
                ),
                file=stdout,
            )
            return (
                0
                if args.list or all(item["status"] in {"completed", "refused"} for item in outcomes)
                else 1
            )
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
