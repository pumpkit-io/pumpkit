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


async def create_user(
    db: AsyncSession,
    user: User,
) -> None:
    """Create a new user in the database"""
    db.add(user)
    await db.commit()


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
