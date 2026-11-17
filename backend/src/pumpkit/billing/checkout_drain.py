"""Preview and drain this Instance's owned Checkouts through the operator boundary."""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import timedelta
from typing import Optional, Sequence, TextIO

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from pumpkit.auth.service import users
from pumpkit.billing import checkout_coordination as coordination
from pumpkit.billing import checkout_evidence, checkout_inventory, mediator, paid_signups, service
from pumpkit.billing.gateway import (
    BillingGateway,
    BillingProviderError,
    CheckoutOutcomeUnknown,
    get_billing_gateway,
)
from pumpkit.core.config import settings
from pumpkit.core.db.session import _db_session_handler
from pumpkit.core.errors import AppError
from pumpkit.core.ids import ulid_with_prefix
from pumpkit.core.time import Clock, as_utc, system_clock


async def _lock_user(db, user_id: str, clock: Clock):
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(text("SET LOCAL lock_timeout = '1000ms'"))
    return await users.require_locked_user(db, user_id=user_id, clock=clock)


async def run_cli(
    argv: Sequence[str],
    *,
    sessions=_db_session_handler.async_session_maker,
    gateway: Optional[BillingGateway] = None,
    stdout: TextIO = sys.stdout,
    clock: Clock = system_clock,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preview", "execute", "status", "release"])
    parser.add_argument("--evidence")
    parser.add_argument("--reviewed-evidence-sha256")
    parser.add_argument("--generation", type=int)
    parser.add_argument("--receipt")
    parser.add_argument("--target-fingerprint")
    parser.add_argument("--recapture-generation", type=int)
    parser.add_argument("--current-fingerprint")
    args = parser.parse_args(argv)
    provider = gateway or get_billing_gateway()
    blockers: list[str] = []
    paused = settings.BILLING_PURCHASES_PAUSED and not settings.BILLING_VERIFICATION_USER_ID
    if not paused and args.command != "release":
        blockers.append("complete_pause_required")
    if not settings.is_stripe_billing_configured():
        blockers.append("billing_not_configured")
    fingerprint = coordination.config_fingerprint()
    result: dict = {
        "schema_version": 1,
        "capability_version": 1,
        "ready": False,
        "fence": {"closed": False, "generation": 0},
        "binding": None,
        "blockers": blockers,
        "proposed_expirations": [],
        "expired": [],
        "completed": [],
        "unknown": [],
        "unresolved_dispatches": [],
        "receipt": None,
        "pending_operations": [],
        "last_release": None,
        "current_config_fingerprint": fingerprint,
    }
    try:
        account_id, livemode = await provider.account_identity()
        async with sessions() as db:
            barrier = await coordination.fence(db, lock=args.command == "execute" and paused)
            capture = bool(
                args.command == "execute" and paused and barrier is not None and not barrier.closed
            )
            if args.recapture_generation is not None:
                if not (
                    args.command == "execute"
                    and paused
                    and barrier
                    and barrier.closed
                    and barrier.generation == args.recapture_generation
                    and args.current_fingerprint == fingerprint
                ):
                    blockers.append("recapture_binding_invalid")
                    capture = False
                else:
                    capture = True
            if capture and barrier is not None:
                barrier.closed = True
                barrier.generation += 1
                barrier.config_fingerprint = fingerprint
                barrier.stable_config_fingerprint = coordination.stable_config_fingerprint()
                barrier.source_managed = settings.STRIPE_MANAGED_PAYMENTS
                barrier.receipt = None
                barrier.evidence_digest = None
                # A new closed source generation retains all old intents and requires fresh review.
                await db.commit()
            release_replayed = bool(
                args.command == "release"
                and barrier
                and not barrier.closed
                and barrier.released_receipt == args.receipt
                and args.receipt
                and barrier.released_generation == args.generation
                and barrier.generation == args.generation + 1
                and barrier.released_fingerprint == args.target_fingerprint == fingerprint
                and barrier.released_evidence_digest == args.reviewed_evidence_sha256
            )
            if barrier:
                result["last_release"] = coordination.release_record(barrier)
                result["fence"] = {"closed": barrier.closed, "generation": barrier.generation}
                result["binding"] = {
                    "instance_id": barrier.instance_id,
                    "generation": barrier.released_generation
                    if release_replayed
                    else barrier.generation,
                    "config_fingerprint": barrier.config_fingerprint or fingerprint,
                    "account_id": account_id,
                    "livemode": livemode,
                }
                source_changed = barrier.closed and barrier.config_fingerprint != fingerprint
                if source_changed and args.command != "release":
                    blockers.append("configuration_changed")
                if not barrier.closed and not release_replayed:
                    blockers.append("fence_open")
            else:
                blockers.append("fence_open")
            evidence, reason = checkout_evidence.load(
                args.evidence, args.reviewed_evidence_sha256, result["binding"] or {}
            )
            if reason:
                blockers.append(reason)
            if args.command == "release" and not release_replayed:
                if not (
                    barrier
                    and barrier.closed
                    and barrier.receipt
                    and args.receipt == barrier.receipt
                    and args.generation == barrier.generation
                    and args.target_fingerprint == fingerprint
                    and barrier.stable_config_fingerprint
                    == coordination.stable_config_fingerprint()
                    and (
                        (settings.STRIPE_MANAGED_PAYMENTS and barrier.source_managed is not None)
                        or (
                            barrier.source_managed is False
                            and not settings.STRIPE_MANAGED_PAYMENTS
                            and paused
                        )
                    )
                    and args.reviewed_evidence_sha256 == barrier.evidence_digest
                ):
                    blockers.append("release_binding_invalid")
            dispatches = await coordination.dispatches(db)
            relationships = await checkout_inventory.relationships(db)
            known_ids = list(relationships.sessions)
            # End the snapshot before taking User locks; the global fence is never held across them.
            await db.commit()
        if release_replayed and not blockers:
            result["released"] = True
            result["release_replayed"] = True
            print(json.dumps(result), file=stdout)
            return 0
        can_execute = args.command == "execute" and not blockers
        inventory = {s.id: s for s in await provider.list_open_checkouts()}
        evidence_ids = (
            {r.session_id for r in evidence.legacy.requests if r.session_id} if evidence else set()
        )
        if evidence:
            known_ids += list(evidence_ids)
        if can_execute and evidence:
            for proof in evidence.legacy.requests:
                if not proof.paid_signup_id:
                    continue
                try:
                    async with sessions() as db:
                        operation = await paid_signups.legacy_review_target(
                            db, operation_id=proof.paid_signup_id
                        )
                        if operation is None:
                            blockers.append("legacy_operation_unverified")
                            continue
                        await _lock_user(db, operation.user_id, clock)
                        if not await paid_signups.resolve_reviewed_legacy_absence(
                            db, provider, proof=proof, now=clock()
                        ):
                            blockers.append("legacy_operation_unverified")
                        await db.commit()
                except (AppError, SQLAlchemyError, KeyError, OSError, TimeoutError):
                    blockers.append("legacy_operation_unverified")
        for dispatch in dispatches:
            if dispatch.session_id:
                known_ids.append(dispatch.session_id)
            if not dispatch.settled:
                matches = [
                    s
                    for s in inventory.values()
                    if s.metadata.get("pumpkit_dispatch") == dispatch.id
                ]
                if can_execute:
                    try:
                        async with sessions() as db:
                            await _lock_user(db, dispatch.user_id, clock)
                            current = await coordination.get_dispatch(db, dispatch.id)
                            resolution = (
                                next(
                                    (
                                        r
                                        for r in evidence.dispatch_resolutions
                                        if r.dispatch_id == current.id
                                    ),
                                    None,
                                )
                                if evidence
                                else None
                            )
                            if resolution:
                                parameters_digest = hashlib.sha256(
                                    json.dumps(current.parameters, sort_keys=True).encode()
                                ).hexdigest()
                                key_digest = hashlib.sha256(
                                    current.idempotency_key.encode()
                                ).hexdigest()
                                if (
                                    resolution.parameters_sha256 != parameters_digest
                                    or resolution.idempotency_key_sha256 != key_digest
                                ):
                                    raise BillingProviderError(
                                        "Reviewed dispatch resolution does not match original intent"
                                    )
                                if resolution.outcome == "provider_resolved_no_object":
                                    if current.session_id or matches:
                                        raise BillingProviderError(
                                            "No-object evidence contradicts an attributable Session"
                                        )
                                    current.provider_finished = True
                                    current.provider_resolution_required = False
                                    current.settled = True
                                    await db.commit()
                                    dispatch.settled = True
                                    continue
                                if (
                                    current.session_id
                                    and current.session_id != resolution.session_id
                                ):
                                    raise BillingProviderError(
                                        "Reviewed object contradicts the retained Session"
                                    )
                                current.provider_finished = True
                                current.provider_resolution_required = False
                                current.session_id = resolution.session_id
                            if (
                                not current.provider_finished
                                or current.provider_resolution_required
                            ):
                                raise BillingProviderError(
                                    "Original invocation needs positive worker and provider resolution"
                                )
                            if current.session_id:
                                session_id = current.session_id
                            elif len(matches) == 1:
                                candidate = matches[0]
                                current.session_id = candidate.id
                                owner, _ = checkout_inventory.ownership(
                                    candidate,
                                    instance_id=result["binding"]["instance_id"],
                                    dispatches=[current],
                                    relationships=relationships,
                                    livemode=livemode,
                                )
                                if owner != "owned":
                                    raise BillingProviderError(
                                        "Dispatch relationship contradicts provider state"
                                    )
                                session_id = candidate.id
                            elif (
                                len(matches) > 1
                                or as_utc(current.attempted_at) + timedelta(hours=24) <= clock()
                            ):
                                raise BillingProviderError(
                                    "Original dispatch needs provider-supported resolution"
                                )
                            else:
                                # Replay only the committed original key and parameters, never a new purchase.
                                current.provider_finished = False
                                # A restarted operator must also prove its prior invocation finished.
                                await db.commit()
                                await _lock_user(db, dispatch.user_id, clock)
                                current = await coordination.get_dispatch(db, dispatch.id)
                                if current.settled or current.provider_finished:
                                    raise BillingProviderError(
                                        "Dispatch ownership changed during reconciliation"
                                    )
                                try:
                                    resolved = await provider.dispatch_checkout(
                                        parameters=current.parameters,
                                        idempotency_key=current.idempotency_key,
                                    )
                                except Exception as error:
                                    current.provider_finished = True
                                    current.provider_resolution_required = isinstance(
                                        error, CheckoutOutcomeUnknown
                                    )
                                    await db.commit()
                                    raise
                                current.provider_finished = True
                                session_id = resolved.id
                            state = await provider.read_checkout(session_id=session_id)
                            current.session_id = session_id
                            owner, _ = checkout_inventory.ownership(
                                state,
                                instance_id=result["binding"]["instance_id"],
                                dispatches=[current],
                                relationships=relationships,
                                livemode=livemode,
                            )
                            if owner != "owned":
                                raise BillingProviderError(
                                    "Resolved dispatch ownership is inconsistent"
                                )
                            current.session_id = session_id
                            current.settled = True
                            await db.commit()
                            dispatch.session_id = session_id
                            dispatch.settled = True
                            known_ids.append(session_id)
                    except (AppError, SQLAlchemyError, KeyError, OSError, TimeoutError):
                        result["unresolved_dispatches"].append(dispatch.id)
                else:
                    result["unresolved_dispatches"].append(dispatch.id)
        for session_id in set(known_ids):
            try:
                inventory[session_id] = await provider.read_checkout(session_id=session_id)
            except (AppError, KeyError, OSError, TimeoutError):
                result["unknown"].append(session_id)
        for session in inventory.values():
            owner, user_id = checkout_inventory.ownership(
                session,
                instance_id=result["binding"]["instance_id"] if result["binding"] else None,
                dispatches=dispatches,
                relationships=relationships,
                livemode=livemode,
            )
            if owner == "foreign":
                if session.id in evidence_ids:
                    result["unknown"].append(session.id)
                continue
            if owner != "owned" or not user_id:
                result["unknown"].append(session.id)
                continue
            if session.managed_payments:
                if session.status == "open":
                    blockers.append("unexpected_managed_checkout")
                continue
            if session.status == "open":
                result["proposed_expirations"].append(session.id)
            if can_execute:
                try:
                    async with sessions() as db:
                        await _lock_user(db, user_id, clock)
                        state = await provider.read_checkout(session_id=session.id)
                        owner, _ = checkout_inventory.ownership(
                            state,
                            instance_id=result["binding"]["instance_id"],
                            dispatches=dispatches,
                            relationships=relationships,
                            livemode=livemode,
                        )
                        if owner != "owned":
                            raise BillingProviderError(
                                "Current Checkout ownership contradicts inventory"
                            )
                        if state.status == "open":
                            try:
                                await provider.expire_checkout(session_id=state.id)
                            except BillingProviderError:
                                pass
                            state = await provider.read_checkout(session_id=state.id)
                        owner, _ = checkout_inventory.ownership(
                            state,
                            instance_id=result["binding"]["instance_id"],
                            dispatches=dispatches,
                            relationships=relationships,
                            livemode=livemode,
                        )
                        if owner != "owned":
                            result["unknown"].append(state.id)
                        elif state.status == "expired":
                            result["expired"].append(state.id)
                        elif state.status == "complete" and state.payment_status in {
                            "paid",
                            "no_payment_required",
                        }:
                            states = await service.sync_customer(
                                db, provider, user_id=user_id, customer_id=state.customer_id or ""
                            )
                            await service.sync_top_ups(
                                db, provider, user_id=user_id, customer_id=state.customer_id or ""
                            )
                            confirmed = await coordination.checkout_benefit_confirmed(
                                db,
                                user_id=user_id,
                                session_id=state.id,
                                mode=state.mode,
                                subscription_id=state.subscription_id,
                            )
                            if state.mode == "subscription":
                                confirmed = confirmed and any(
                                    s.id == state.subscription_id for s in states
                                )
                            else:
                                purchases = await provider.list_top_ups(
                                    customer_id=state.customer_id or ""
                                )
                                confirmed = confirmed and any(
                                    p.checkout_session_id == state.id for p in purchases
                                )
                            await coordination.record_benefit_confirmation(
                                db, session_id=state.id, confirmed=confirmed
                            )
                            if confirmed:
                                result["completed"].append(state.id)
                            else:
                                blockers.append("completed_purchase_unconfirmed")
                        else:
                            result["unknown"].append(state.id)
                        await db.commit()
                except (AppError, SQLAlchemyError, KeyError, OSError, TimeoutError):
                    result["unknown"].append(session.id)
            elif session.status == "open" or (
                session.status == "complete"
                and session.payment_status not in {"paid", "no_payment_required"}
            ):
                blockers.append("owned_checkout_unsettled")
        if can_execute:
            async with sessions() as db:
                pending = [(op.user_id, op.operation_id) for op in await paid_signups.pending(db)]
                await db.commit()
            for user_id, operation_id in pending:
                try:
                    async with sessions() as db:
                        user = await _lock_user(db, user_id, clock)
                        await mediator.lookup_paid_signup(
                            db, provider, user, operation_id=operation_id, clock=clock
                        )
                except (AppError, SQLAlchemyError, OSError, TimeoutError):
                    blockers.append("pending_operation_unresolved")
        async with sessions() as db:
            result["pending_operations"] = await coordination.pending_operations(db)
            if result["pending_operations"]:
                blockers.append("pending_operation_unresolved")
            if any(not d.settled for d in await coordination.dispatches(db)):
                blockers.append("dispatch_unresolved")
            if result["unknown"]:
                blockers.append("ownership_or_state_unverified")
            if result["unresolved_dispatches"]:
                blockers.append("dispatch_unresolved")
            await db.commit()
            barrier = await coordination.fence(db, lock=args.command in {"execute", "release"})
            if (
                not barrier
                or not barrier.closed
                or result["fence"]["generation"] != barrier.generation
            ):
                blockers.append("fence_changed")
            confirmed_receipt = None
            confirmed_release = None
            if barrier and args.command == "execute":
                if not blockers:
                    barrier.receipt = barrier.receipt or ulid_with_prefix("drain")
                    barrier.evidence_digest = args.reviewed_evidence_sha256
                    confirmed_receipt = barrier.receipt
                else:
                    barrier.receipt = None
                    barrier.evidence_digest = None
            elif barrier and args.command == "status" and not blockers:
                if barrier.receipt and barrier.evidence_digest == args.reviewed_evidence_sha256:
                    confirmed_receipt = barrier.receipt
            elif barrier and args.command == "release" and not blockers:
                if (
                    barrier.receipt != args.receipt
                    or barrier.evidence_digest != args.reviewed_evidence_sha256
                ):
                    blockers.append("release_binding_changed")
                else:
                    barrier.released_receipt = barrier.receipt
                    barrier.released_generation = barrier.generation
                    barrier.released_fingerprint = fingerprint
                    barrier.released_evidence_digest = barrier.evidence_digest
                    barrier.closed = False
                    barrier.generation += 1
                    barrier.receipt = None
                    barrier.evidence_digest = None
                    confirmed_release = coordination.release_record(barrier)
            await db.commit()
            if confirmed_receipt:
                result["receipt"] = confirmed_receipt
                result["ready"] = True
            if confirmed_release:
                result["fence"] = {"closed": False, "generation": confirmed_release["generation"]}
                result["last_release"] = confirmed_release
                result["released"] = True
    except (AppError, SQLAlchemyError, KeyError, OSError, TimeoutError):
        blockers.append("provider_or_coordination_unavailable")
    if blockers:
        result["ready"] = False
        result["receipt"] = None
        result.pop("released", None)
    result["blockers"] = sorted(set(blockers))
    for field in [
        "proposed_expirations",
        "expired",
        "completed",
        "unknown",
        "unresolved_dispatches",
    ]:
        result[field] = sorted(set(result[field]))
    print(json.dumps(result), file=stdout)
    return 0 if result["ready"] or result.get("released") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_cli(sys.argv[1:])))
