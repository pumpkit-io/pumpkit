import hashlib
import json
import secrets
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.billing.models import (
    CheckoutDispatch,
    CheckoutFence,
    CouponOperation,
    PaidSignup,
    PlanChange,
    Subscription,
    TopUp,
)
from pumpkit.billing.purchase_availability import PurchasesPausedError
from pumpkit.core.config import Settings, settings
from pumpkit.core.errors import ConflictError
from pumpkit.core.ids import ulid_with_prefix


def config_fingerprint(configuration: Settings = settings) -> str:
    values = configuration.model_dump(mode="json")
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


async def fence(db: AsyncSession, *, lock: bool = False) -> Optional[CheckoutFence]:
    if lock:
        insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
        await db.execute(
            insert(CheckoutFence)
            .values(
                id=1,
                instance_id=secrets.token_hex(24),
                generation=0,
                closed=False,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
    query = (
        select(CheckoutFence).where(CheckoutFence.id == 1).execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    return await db.scalar(query)


async def register(
    db: AsyncSession,
    *,
    user_id: str,
    kind: str,
    parameters: dict,
    now: datetime,
    operation_id: Optional[str] = None,
) -> CheckoutDispatch:
    barrier = await fence(db, lock=True)
    if barrier is None:
        raise ConflictError("Checkout coordination is not initialized. Contact support.")
    if barrier.closed:
        raise PurchasesPausedError()
    dispatch_id = operation_id or ulid_with_prefix("checkout")
    existing = await db.get(CheckoutDispatch, dispatch_id)
    if existing:
        return existing
    metadata = {
        **parameters.get("metadata", {}),
        "pumpkit_instance": barrier.instance_id,
        "pumpkit_dispatch": dispatch_id,
        "pumpkit_kind": kind,
    }
    pinned = {**parameters, "metadata": metadata}
    dispatch = CheckoutDispatch(
        id=dispatch_id,
        user_id=user_id,
        kind=kind,
        generation=barrier.generation,
        parameters=pinned,
        idempotency_key=f"{dispatch_id}:checkout",
        attempted_at=now,
    )
    db.add(dispatch)
    await db.flush()
    return dispatch


async def dispatches(db: AsyncSession) -> list[CheckoutDispatch]:
    return list(await db.scalars(select(CheckoutDispatch)))


async def require_settled(db: AsyncSession, *, user_id: str) -> None:
    if await db.scalar(
        select(PaidSignup.id).where(
            PaidSignup.user_id == user_id,
            PaidSignup.status == "pending",
            PaidSignup.checkout_contract != 1,
        )
    ):
        raise ConflictError(
            "Your original checkout request needs support review before another purchase or account deletion."
        )
    if await db.scalar(
        select(CheckoutDispatch.id).where(
            CheckoutDispatch.user_id == user_id, CheckoutDispatch.settled.is_(False)
        )
    ):
        raise ConflictError(
            "Your checkout is being confirmed. Contact support before changing billing or deleting your account."
        )


async def get_dispatch(db: AsyncSession, dispatch_id: str) -> CheckoutDispatch:
    result = await db.get(CheckoutDispatch, dispatch_id, populate_existing=True)
    if result is None:
        raise ConflictError("Checkout evidence is unavailable. Contact support.")
    return result


def stable_config_fingerprint() -> str:
    values = settings.model_dump(mode="json")
    for key in [
        "STRIPE_MANAGED_PAYMENTS",
        "BILLING_PURCHASES_PAUSED",
        "BILLING_VERIFICATION_USER_ID",
    ]:
        values.pop(key, None)
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


async def pending_operations(db: AsyncSession) -> list[dict[str, str]]:
    pending = []
    for kind, model in [
        ("coupon", CouponOperation),
        ("arranged_paid_signup", PaidSignup),
        ("plan_change", PlanChange),
    ]:
        pending.extend(
            {"kind": kind, "id": id}
            for id in await db.scalars(select(model.id).where(model.status == "pending"))
        )
    return pending


async def observed_paid_signup(db: AsyncSession, *, operation_id: str, session_id: str) -> None:
    dispatch = await db.get(CheckoutDispatch, operation_id)
    if dispatch and dispatch.kind == "arranged_paid_signup":
        if dispatch.session_id and dispatch.session_id != session_id:
            raise ConflictError("Multiple checkout results need support review.")
        dispatch.session_id = session_id
        dispatch.settled = dispatch.provider_finished and not dispatch.provider_resolution_required
        await db.flush()


async def unresolved_paid_signup(db: AsyncSession, *, operation_id: str) -> bool:
    dispatch = await db.get(CheckoutDispatch, operation_id)
    return dispatch is not None and not dispatch.settled


async def checkout_benefit_confirmed(
    db: AsyncSession, *, user_id: str, session_id: str, mode: str, subscription_id: Optional[str]
) -> bool:
    if mode == "payment":
        return bool(
            await db.scalar(
                select(TopUp.id).where(
                    TopUp.user_id == user_id, TopUp.stripe_checkout_session_id == session_id
                )
            )
        )
    if not subscription_id:
        return False
    return bool(
        await db.scalar(
            select(Subscription.id).where(
                Subscription.user_id == user_id,
                Subscription.stripe_subscription_id == subscription_id,
            )
        )
    )


async def record_benefit_confirmation(
    db: AsyncSession, *, session_id: str, confirmed: bool
) -> None:
    for dispatch in await db.scalars(
        select(CheckoutDispatch).where(CheckoutDispatch.session_id == session_id)
    ):
        dispatch.settled = (
            confirmed and dispatch.provider_finished and not dispatch.provider_resolution_required
        )
    await db.flush()


def release_record(barrier: CheckoutFence) -> Optional[dict]:
    if not barrier.released_receipt or barrier.released_generation is None:
        return None
    return {
        "receipt": barrier.released_receipt,
        "source_generation": barrier.released_generation,
        "generation": barrier.released_generation + 1,
        "target_fingerprint": barrier.released_fingerprint,
        "evidence_digest": barrier.released_evidence_digest,
    }
