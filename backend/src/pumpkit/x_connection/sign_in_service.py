from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.core.security import decrypt, encrypt, generate_token, hash_token
from pumpkit.core.time import as_utc
from pumpkit.x_connection.models import PendingXSignIn
from pumpkit.x_connection.service import LIFETIME
from pumpkit.x_connection.x_publisher import new_code_verifier


@dataclass(frozen=True)
class StartedSignIn:
    state: str
    browser_secret: str
    code_verifier: str


async def start(db: AsyncSession, *, now: datetime, return_to: Optional[str]) -> StartedSignIn:
    await db.execute(delete(PendingXSignIn).where(PendingXSignIn.expires_at <= now))
    started = StartedSignIn(
        state="signin." + generate_token(32),
        browser_secret=generate_token(32),
        code_verifier=new_code_verifier(),
    )
    db.add(
        PendingXSignIn(
            state_hash=hash_token(started.state),
            browser_secret_hash=hash_token(started.browser_secret),
            code_verifier_encrypted=encrypt(started.code_verifier),
            return_to=return_to,
            created_at=now,
            expires_at=now + LIFETIME,
        )
    )
    await db.flush()
    return started


@dataclass(frozen=True)
class ConsumedSignIn:
    code_verifier: str
    return_to: Optional[str]


async def consume(
    db: AsyncSession, *, state: str, browser_secret: str, now: datetime
) -> Optional[ConsumedSignIn]:
    # DELETE RETURNING gives concurrent callbacks a single winner without exposing the verifier.
    deleted = await db.execute(
        delete(PendingXSignIn)
        .where(
            PendingXSignIn.state_hash == hash_token(state),
            PendingXSignIn.browser_secret_hash == hash_token(browser_secret),
        )
        .returning(
            PendingXSignIn.code_verifier_encrypted,
            PendingXSignIn.return_to,
            PendingXSignIn.expires_at,
        )
    )
    row = deleted.one_or_none()
    if row is None or as_utc(row.expires_at) <= now:
        return None
    verifier = decrypt(row.code_verifier_encrypted)
    return ConsumedSignIn(code_verifier=verifier, return_to=row.return_to) if verifier else None
