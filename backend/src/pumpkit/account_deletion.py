"""
Deletes a settled account and its stored files: a User's own deletion from Settings (ADR 0031),
and the Operator's command for a User who wrote to support.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Optional, TextIO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import pumpkit.models  # noqa: F401
from pumpkit.auth.models import User
from pumpkit.auth.service import users
from pumpkit.billing import coupon_operations, coupon_redemption, prelaunch_reset
from pumpkit.billing import service as billing
from pumpkit.billing.gateway import BillingGateway, get_billing_gateway
from pumpkit.billing.models import FreeAccess
from pumpkit.core.background import TaskRegistry
from pumpkit.core.db.session import _db_session_handler
from pumpkit.core.errors import AppError, ConflictError, RefusedError
from pumpkit.core.logging import logger
from pumpkit.core.storage import FileStorage, get_file_storage
from pumpkit.posts import account_deletion as post_deletion
from pumpkit.posts.models import AccountFileDeletion, Media
from pumpkit.scheduling import service as scheduling
from pumpkit.x_connection import service as x_connection
from pumpkit.x_connection.x_publisher import XPublisher, XPublisherError

PUBLISHING_IN_PROGRESS = "publishing_in_progress"
BILLING_OPERATION_PENDING = "billing_operation_pending"
UNPAID_INVOICE = "unpaid_invoice"
SUBSCRIPTION_RUNNING = "subscription_running"

# The command prints each refusal's own words; a User deleting from Settings reads these.
_USER_MESSAGES = {
    PUBLISHING_IN_PROGRESS: "A post is going out on X right now. Try again in a minute.",
    BILLING_OPERATION_PENDING: (
        "A billing change is still being processed. Try again in a few minutes."
    ),
    UNPAID_INVOICE: "You have an unpaid invoice. Contact support to delete your account.",
    SUBSCRIPTION_RUNNING: (
        "Your subscription is still running. Cancel it in Plan, then delete your account"
        " once it has ended."
    ),
}


@dataclass(frozen=True)
class ResetReport:
    coupon_claims: int
    trial_eligibility: int
    file_keys: frozenset[str]


async def delete_account(
    db: AsyncSession,
    gateway: BillingGateway,
    *,
    user_id: str,
    reset_benefits: bool = False,
    dry_run: bool = False,
) -> Optional[ResetReport]:
    user = await users.get_user_by_id(db, user_id)
    if user is None:
        if reset_benefits:
            raise ConflictError("The selected prelaunch account does not exist.")
        return
    locked = await users.lock_user_id(db, user_id=user.id)
    if locked is None:
        if reset_benefits:
            raise ConflictError("The selected prelaunch account does not exist.")
        return
    user = locked
    try:
        await coupon_operations.require_settled(db, user_id=user.id)
    except ConflictError as error:
        raise ConflictError(error.detail, code=BILLING_OPERATION_PENDING) from error
    try:
        await scheduling.require_settled_publishing_before_account_deletion(db, user_id=user.id)
    except ConflictError as error:
        raise ConflictError(error.detail, code=PUBLISHING_IN_PROGRESS) from error
    if user.stripe_customer_id:
        states = await gateway.list_subscriptions(customer_id=user.stripe_customer_id)
        if await gateway.has_pending_checkout(customer_id=user.stripe_customer_id):
            raise ConflictError(
                "Resolve the pending paid checkout before deleting this account.",
                code=BILLING_OPERATION_PENDING,
            )
        if any(state.status not in {"canceled", "incomplete_expired"} for state in states):
            raise ConflictError(
                "Resolve outstanding subscription and payment obligations before deleting this account.",
                code=SUBSCRIPTION_RUNNING,
            )
        if await gateway.has_unsettled_invoices(customer_id=user.stripe_customer_id):
            raise ConflictError(
                "Resolve outstanding subscription and payment obligations before deleting this account.",
                code=UNPAID_INVOICE,
            )
        await billing.sync_customer(
            db, gateway, user_id=user.id, customer_id=user.stripe_customer_id
        )
    if await billing.get_user_subscription(db, user_id=user.id):
        raise ConflictError(
            "Resolve the account's subscription before deletion.", code=SUBSCRIPTION_RUNNING
        )
    benefit_reset = await prelaunch_reset.prepare(db, user=user) if reset_benefits else None
    file_keys = frozenset(
        key
        for media in await db.scalars(select(Media).where(Media.user_id == user.id))
        for key in (media.file_key, media.preview_key)
        if key is not None
    )
    report = (
        ResetReport(len(benefit_reset.claims), len(benefit_reset.trials), file_keys)
        if benefit_reset is not None
        else None
    )
    if dry_run:
        await db.rollback()
        return report
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
    if benefit_reset is None:
        await billing.preserve_trial_eligibility(db, user_id=user.id)
    await users.delete_account(db, user)
    if benefit_reset is not None:
        await prelaunch_reset.apply(db, benefit_reset)
    await db.commit()
    return report


async def delete_own_account(
    db: AsyncSession,
    gateway: BillingGateway,
    publisher: XPublisher,
    tasks: TaskRegistry,
    sessions: async_sessionmaker[AsyncSession],
    storage: FileStorage,
    *,
    user: User,
    handle: str,
) -> None:
    """
    Delete the signed-in User's account once they typed their handle, then revoke Pumpkit's X
    grant and delete their Media files in the background. Sessions and Connected apps cascade.
    """
    if not _confirms(user, handle):
        raise RefusedError("Type your @handle to confirm.", code="handle_mismatch")
    # The cascade removes the X connection, so its token is read first.
    connection = await x_connection.get_connection(db, user_id=user.id)
    refresh_token = x_connection.refresh_token(connection) if connection is not None else None
    try:
        await delete_account(db, gateway, user_id=user.id)
    except ConflictError as error:
        if error.code not in _USER_MESSAGES:
            raise
        raise ConflictError(_USER_MESSAGES[error.code], code=error.code) from error
    if refresh_token:
        try:
            await publisher.revoke(token=refresh_token, token_type_hint="refresh_token")
        except XPublisherError as error:
            # The tokens are gone from Pumpkit either way, so the deletion stands.
            logger.warning("Revoking a deleted account's X token failed: %s", error)
    await tasks.start(f"delete the files of deleted account {user.id}", _sweep(sessions, storage))


def _confirms(user: User, handle: str) -> bool:
    typed = handle.strip().removeprefix("@").casefold()
    return user.x_handle is not None and typed == user.x_handle.casefold()


async def _sweep(sessions: async_sessionmaker[AsyncSession], storage: FileStorage) -> None:
    # A failed sweep leaves the files queued for the next one, or for `--retry-files`.
    async with sessions() as db:
        await delete_files(db, storage)


async def delete_files(
    db: AsyncSession, storage: FileStorage, *, only_keys: Optional[frozenset[str]] = None
) -> None:
    for pending in await post_deletion.pending_files(db):
        if only_keys is not None and pending.key not in only_keys:
            continue
        await storage.delete(pending.key)
        await db.delete(pending)
    if only_keys and await db.scalar(
        select(AccountFileDeletion.key).where(AccountFileDeletion.key.in_(only_keys)).limit(1)
    ):
        raise ConflictError("Selected file cleanup is still pending. Retry with --retry-files.")
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
    parser.add_argument(
        "--prelaunch-reset",
        action="store_true",
        help="Preview deletion of one selected prelaunch account and its benefit fingerprints.",
    )
    parser.add_argument(
        "--execute", action="store_true", help="Commit the prelaunch reset instead of previewing."
    )
    args = parser.parse_args(argv)
    if args.prelaunch_reset and not args.user_id:
        parser.error("--prelaunch-reset requires --user-id")
    if args.execute and not args.prelaunch_reset:
        parser.error("--execute requires --prelaunch-reset")
    try:
        report = None
        async with sessions() as db:
            if args.user_id:
                report = await delete_account(
                    db,
                    gateway,
                    user_id=args.user_id,
                    reset_benefits=args.prelaunch_reset,
                    dry_run=args.prelaunch_reset and not args.execute,
                )
            if not args.prelaunch_reset or args.execute:
                await delete_files(
                    db, storage, only_keys=report.file_keys if report is not None else None
                )
        if report is not None:
            print(
                json.dumps(
                    {
                        "executed": args.execute,
                        "users": 1,
                        "coupon_claims": report.coupon_claims,
                        "trial_eligibility": report.trial_eligibility,
                        "files": len(report.file_keys),
                    }
                ),
                file=stdout,
            )
            return 0
        print("Account deletion and queued file cleanup completed.", file=stdout)
        return 0
    except Exception as exc:
        detail = (
            str(exc.response_body()["detail"])
            if isinstance(exc, AppError)
            else (
                "Reset or file cleanup failed. Check account state; use --retry-files for committed deletions."
                if args.prelaunch_reset
                else "Deletion or file cleanup failed. Retry the command; queued files remain pending."
            )
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
