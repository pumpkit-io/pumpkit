from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User


async def get_user_by_email(
    db: AsyncSession,
    email: str,
) -> Optional[User]:
    query = select(User).where(User.email == email)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_user_by_id(
    db: AsyncSession,
    user_id: str,
) -> Optional[User]:
    query = select(User).where(User.id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_user_by_stripe_customer_id(
    db: AsyncSession,
    stripe_customer_id: str,
) -> Optional[User]:
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
    Every Sign-in method resolves through here, so one email always reaches one User.
    Flushes, never commits: the sign-in commits once with its Session.
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
    Lock and reload the User's row until the transaction ends, serializing billing steps per User.
    SQLite has no row locks: there it only reloads.
    """
    query = (
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    await db.execute(query)


async def set_stripe_customer_id(db: AsyncSession, user: User, stripe_customer_id: str) -> None:
    """Flushes, never commits."""
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


def may_fill_photo(user: User) -> bool:
    """Whether Pumpkit may give the User a Photo on its own: they have none and never chose one."""
    return user.avatar_data_url is None and user.photo_chosen_at is None


async def fill_photo(db: AsyncSession, user: User, photo_data_url: str) -> None:
    """
    Give the User a Photo they didn't choose, such as their Google picture, only while
    `may_fill_photo`. Leaves the Photo chosen marker unset. Flushes, never commits.
    """
    if not may_fill_photo(user):
        return
    user.avatar_data_url = photo_data_url
    await db.flush()


async def choose_photo(
    db: AsyncSession, user: User, photo_data_url: Optional[str], now: datetime
) -> None:
    """
    Save the Photo the User chose, or clear it with `None`, and mark the Photo chosen, so
    Pumpkit never fills it again. Flushes, never commits.
    """
    user.avatar_data_url = photo_data_url
    if user.photo_chosen_at is None:
        user.photo_chosen_at = now
    await db.flush()


async def update_user_profile(
    db: AsyncSession, user: User, changes: dict[str, Any], now: datetime
) -> User:
    """
    Apply profile changes. Flushes, never commits.

    A first or last name change re-derives display_name, which the app shows for the User;
    clearing both falls back to the email local part. Saving or clearing the Photo marks it chosen.
    """
    changes = dict(changes)
    if "avatar_data_url" in changes:
        await choose_photo(db, user, changes.pop("avatar_data_url"), now)
    for field, value in changes.items():
        setattr(user, field, value)

    if "first_name" in changes or "last_name" in changes:
        derived = " ".join(part for part in (user.first_name, user.last_name) if part).strip()
        user.display_name = derived or user.email.split("@", 1)[0]

    await db.flush()
    return user
