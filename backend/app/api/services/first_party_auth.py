from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.services.users import get_user_by_email
from app.core.security import verify_password
from app.db.models import (
    EmailVerification,
    FirstPartyAuth,
    PasswordReset,
    User,
)


async def create_first_party_auth(
    db: AsyncSession,
    first_party_auth: FirstPartyAuth,
) -> None:
    """Create a new first-party auth record in the database"""
    db.add(first_party_auth)
    await db.commit()


async def create_email_verification(
    db: AsyncSession,
    email_verification: EmailVerification,
) -> None:
    """Create a new email verification in the database"""
    db.add(email_verification)
    await db.commit()


async def get_latest_email_verification_by_user_id(
    db: AsyncSession,
    user_id: str,
) -> Optional[EmailVerification]:
    """Get the most recently sent email verification for a user."""
    query = (
        select(EmailVerification)
        .where(EmailVerification.user_id == user_id)
        .order_by(EmailVerification.sent_at.desc())
        .limit(1)
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_email_verification_by_token_hash(
    db: AsyncSession,
    token_hash: str,
) -> Optional[EmailVerification]:
    """Get an email verification by its token hash"""
    query = select(EmailVerification).where(EmailVerification.token_hash == token_hash)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def mark_email_verification_consumed(
    db: AsyncSession,
    email_verification: EmailVerification,
) -> None:
    """Mark an email verification as consumed"""
    email_verification.consumed_at = datetime.now(timezone.utc)
    await db.commit()


async def atomically_consume_email_verification_and_verify_user(
    db: AsyncSession,
    token_hash: str,
) -> Optional[EmailVerification]:
    """
    Atomically mark an email verification as consumed and set the user's email as verified.
    Returns None if the token was already consumed (race condition).
    """
    now = datetime.now(timezone.utc)

    # Mark the email verification token as consumed
    query = (
        update(EmailVerification)
        .where(
            EmailVerification.token_hash == token_hash,
            EmailVerification.consumed_at.is_(None),
        )
        .values(consumed_at=now)
        .returning(EmailVerification)
    )
    result = await db.execute(query)
    email_verification = result.scalar_one_or_none()

    if email_verification is None:
        return None

    # Mark first-party auth as verified in the same transaction
    await db.execute(
        update(FirstPartyAuth)
        .where(FirstPartyAuth.user_id == email_verification.user_id)
        .values(is_email_verified=True)
    )

    # Commit everything at the end - if any part of this fails, the transaction
    # will be rolled back and the email verification token will not be consumed
    await db.commit()
    return email_verification


async def mark_first_party_auth_verified(
    db: AsyncSession,
    user_id: str,
) -> None:
    """Mark a first-party auth record as email verified"""
    query = select(FirstPartyAuth).where(FirstPartyAuth.user_id == user_id)
    result = await db.execute(query)
    first_party_auth = result.scalar_one_or_none()
    if first_party_auth:
        first_party_auth.is_email_verified = True
        await db.commit()


async def get_first_party_auth_by_user_id(
    db: AsyncSession,
    user_id: str,
) -> Optional[FirstPartyAuth]:
    """Get first-party auth by user ID"""
    query = select(FirstPartyAuth).where(FirstPartyAuth.user_id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def authenticate_user(
    db: AsyncSession,
    email: str,
    password: str,
) -> Optional[User]:
    """Authenticate a user with email and password"""

    # Get user by email
    user = await get_user_by_email(db=db, email=email)
    if not user:
        return None

    # Check if user account is active
    if not user.is_active:
        return None

    # Check if user is banned
    if user.banned_until and user.banned_until > datetime.now(timezone.utc):
        return None

    # Get local credentials
    first_party_auth = await get_first_party_auth_by_user_id(db=db, user_id=user.id)
    if not first_party_auth:
        return None

    # Check if email is verified
    if not first_party_auth.is_email_verified:
        return None

    # Verify password
    if not verify_password(password, first_party_auth.password_hash):
        return None

    return user


async def is_email_verified(
    db: AsyncSession,
    user_id: str,
) -> bool:
    """Check if user's email is verified"""
    first_party_auth = await get_first_party_auth_by_user_id(db=db, user_id=user_id)
    return first_party_auth.is_email_verified if first_party_auth else False


async def invalidate_password_resets_for_user(
    db: AsyncSession,
    user_id: str,
) -> None:
    """Mark any outstanding password reset tokens for a user as consumed."""
    await db.execute(
        update(PasswordReset)
        .where(PasswordReset.user_id == user_id, PasswordReset.consumed_at.is_(None))
        .values(consumed_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def create_password_reset(
    db: AsyncSession,
    password_reset: PasswordReset,
) -> None:
    """Persist a new password reset token."""
    db.add(password_reset)
    await db.commit()


async def get_password_reset_by_token_hash(
    db: AsyncSession,
    token_hash: str,
) -> Optional[PasswordReset]:
    """Fetch a password reset entry by hashed token."""
    query = select(PasswordReset).where(PasswordReset.token_hash == token_hash)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def mark_password_reset_consumed(
    db: AsyncSession,
    password_reset: PasswordReset,
) -> None:
    """Mark a password reset token as used."""

    password_reset.consumed_at = datetime.now(timezone.utc)
    await db.commit()


async def update_user_password(
    db: AsyncSession,
    user_id: str,
    password_hash: str,
) -> bool:
    """Update the stored password hash for a user."""

    query = select(FirstPartyAuth).where(FirstPartyAuth.user_id == user_id)
    result = await db.execute(query)
    first_party_auth = result.scalar_one_or_none()

    if not first_party_auth:
        return False

    first_party_auth.password_hash = password_hash
    first_party_auth.password_set_at = datetime.now(timezone.utc)
    await db.commit()
    return True


async def atomically_consume_password_reset_and_update_password(
    db: AsyncSession,
    token_hash: str,
    password_hash: str,
) -> Optional[PasswordReset]:
    """
    Atomically mark a password reset token as consumed and update the user's
    password. Returns None if the token was already consumed (race condition).
    """
    now = datetime.now(timezone.utc)

    # Mark the password reset token as consumed
    query = (
        update(PasswordReset)
        .where(
            PasswordReset.token_hash == token_hash,
            PasswordReset.consumed_at.is_(None),
        )
        .values(consumed_at=now)
        .returning(PasswordReset)
    )
    result = await db.execute(query)
    password_reset = result.scalar_one_or_none()

    if password_reset is None:
        return None

    # Update the password in the same transaction
    await db.execute(
        update(FirstPartyAuth)
        .where(FirstPartyAuth.user_id == password_reset.user_id)
        .values(password_hash=password_hash, password_set_at=now)
    )

    await db.commit()
    return password_reset
