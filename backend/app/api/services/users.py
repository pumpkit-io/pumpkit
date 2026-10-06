from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


async def get_user_by_email(
    db: AsyncSession,
    email: str,
) -> Optional[User]:
    """Get a user from the database by their email"""
    query = select(User).where(User.email == email)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_user_by_id(
    db: AsyncSession,
    user_id: str,
) -> Optional[User]:
    """Get a user from the database by their ID"""
    query = select(User).where(User.id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_user_by_stripe_customer_id(
    db: AsyncSession,
    stripe_customer_id: str,
) -> Optional[User]:
    """The User whose Stripe customer this is, if any."""
    query = select(User).where(User.stripe_customer_id == stripe_customer_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


@dataclass(frozen=True)
class NameHints:
    """Names a Sign-in method suggests for a User, used only to fill empty profile fields."""

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    display_name: Optional[str] = None


async def resolve_user_by_verified_email(
    db: AsyncSession,
    email: str,
    hints: NameHints = NameHints(),
) -> User:
    """
    The User a Sign-in method has proven owns this email: found, or created.

    Every Sign-in method resolves through here, so one email always reaches one
    User. The name hints only fill profile fields that are still empty. Flushes,
    never commits: the sign-in commits once with its Session.
    """
    normalized_email = email.strip().lower()
    user = await get_user_by_email(db=db, email=normalized_email)
    if user is None:
        user = User(
            email=normalized_email,
            display_name=hints.display_name or normalized_email.split("@", 1)[0],
            first_name=hints.first_name,
            last_name=hints.last_name,
            is_admin=False,
        )
        db.add(user)
        await db.flush()
        return user

    fill_empty_profile(user, hints)
    await db.flush()
    return user


async def lock_user(db: AsyncSession, user: User) -> None:
    """
    Lock the User's row (`SELECT ... FOR UPDATE`) until the transaction ends,
    and reload its columns, so the caller sees what a request that held the
    lock before it committed. Serializes billing steps per User. SQLite has no
    row locks: there it only reloads.
    """
    query = (
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    await db.execute(query)


async def set_stripe_customer_id(db: AsyncSession, user: User, stripe_customer_id: str) -> None:
    """Record the User's Stripe customer. Flushes, never commits."""
    user.stripe_customer_id = stripe_customer_id
    await db.flush()


def fill_empty_profile(user: User, hints: NameHints) -> None:
    """Fill the User's empty profile fields from name hints, never overwriting what they have."""
    if not user.first_name and hints.first_name:
        user.first_name = hints.first_name
    if not user.last_name and hints.last_name:
        user.last_name = hints.last_name
    if not user.display_name and hints.display_name:
        user.display_name = hints.display_name


async def update_user_profile(db: AsyncSession, user: User, changes: dict[str, Any]) -> User:
    """Apply profile changes to a user and persist them.

    Keeps display_name coherent with first/last name when either changes, since
    display_name is what the rest of the system shows for users without a better
    source. Falls back to the email local part when both names are cleared.
    """
    for field, value in changes.items():
        setattr(user, field, value)

    if "first_name" in changes or "last_name" in changes:
        derived = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
        user.display_name = derived or user.email.split("@", 1)[0]

    await db.commit()
    await db.refresh(user)
    return user
