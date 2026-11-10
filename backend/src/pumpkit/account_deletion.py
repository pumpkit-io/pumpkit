"""Privileged support owner for deleting a settled local account and its stored files."""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from typing import TextIO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import pumpkit.models  # noqa: F401
from pumpkit.auth.service import users
from pumpkit.billing import coupon_operations, coupon_redemption
from pumpkit.billing import service as billing
from pumpkit.billing.gateway import BillingGateway, get_billing_gateway
from pumpkit.billing.models import FreeAccess
from pumpkit.core.db.session import _db_session_handler
from pumpkit.core.errors import AppError, ConflictError
from pumpkit.core.storage import FileStorage, get_file_storage
from pumpkit.posts import account_deletion as post_deletion
from pumpkit.scheduling import service as scheduling


async def delete_account(db: AsyncSession, gateway: BillingGateway, *, user_id: str) -> None:
    user = await users.get_user_by_id(db, user_id)
    if user is None:
        return
    locked = await users.lock_user_id(db, user_id=user.id)
    if locked is None:
        return
    user = locked
    await coupon_operations.require_settled(db, user_id=user.id)
    await scheduling.require_settled_publishing_before_account_deletion(db, user_id=user.id)
    if user.stripe_customer_id:
        states = await gateway.list_subscriptions(customer_id=user.stripe_customer_id)
        if await gateway.has_pending_checkout(customer_id=user.stripe_customer_id):
            raise ConflictError("Resolve the pending paid checkout before deleting this account.")
        if any(
            state.status not in {"canceled", "incomplete_expired"} for state in states
        ) or await gateway.has_unsettled_invoices(customer_id=user.stripe_customer_id):
            raise ConflictError(
                "Resolve outstanding subscription and payment obligations before deleting this account."
            )
        await billing.sync_customer(
            db, gateway, user_id=user.id, customer_id=user.stripe_customer_id
        )
    if await billing.get_user_subscription(db, user_id=user.id):
        raise ConflictError("Resolve the account's subscription before deletion.")
    coupon_ids = list(
        await db.scalars(
            select(FreeAccess.coupon_id)
            .where(FreeAccess.user_id == user.id)
            .distinct()
            .order_by(FreeAccess.coupon_id)
        )
    )
    for coupon_id in coupon_ids:
        await coupon_redemption.lock_coupon(db, coupon_id)
    await post_deletion.queue_files(db, user_id=user.id)
    await billing.preserve_trial_eligibility(db, user_id=user.id)
    await users.delete_account(db, user)
    await db.commit()


async def delete_files(db: AsyncSession, storage: FileStorage) -> None:
    for pending in await post_deletion.pending_files(db):
        await storage.delete(pending.key)
        await db.delete(pending)
    await db.commit()


async def run_cli(
    argv: Sequence[str],
    *,
    sessions: async_sessionmaker[AsyncSession],
    gateway: BillingGateway,
    storage: FileStorage,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m pumpkit.account_deletion")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--user-id")
    group.add_argument("--retry-files", action="store_true")
    args = parser.parse_args(argv)
    try:
        async with sessions() as db:
            if args.user_id:
                await delete_account(db, gateway, user_id=args.user_id)
            await delete_files(db, storage)
        print("Account deletion and queued file cleanup completed.", file=stdout)
        return 0
    except Exception as exc:
        detail = (
            str(exc.response_body()["detail"])
            if isinstance(exc, AppError)
            else "Deletion or file cleanup failed. Retry the command; queued files remain pending."
        )
        print(detail, file=stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(
        asyncio.run(
            run_cli(
                sys.argv[1:],
                sessions=_db_session_handler.async_session_maker,
                gateway=get_billing_gateway(),
                storage=get_file_storage(),
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
        )
    )
