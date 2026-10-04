from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.users as user_service
from app.core.google_sign_in import GoogleClaims
from app.db.models import GoogleIdentity, User


async def get_google_identity(
    db: AsyncSession,
    subject: str,
) -> Optional[GoogleIdentity]:
    """Get a Google identity by its Google subject."""
    query = select(GoogleIdentity).where(GoogleIdentity.subject == subject)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def resolve_user(db: AsyncSession, claims: GoogleClaims) -> User:
    """
    The User these verified Google claims sign in.

    A Google account already linked to a User reaches that User, whatever its
    email is now. Otherwise the User is resolved by the verified email (found or
    created) and the Google account is linked to them. Flushes, never commits.
    """
    google_identity = await get_google_identity(db=db, subject=claims.subject)
    if google_identity is not None:
        # The foreign key cascades on delete, so a Google identity always has its User.
        user = await user_service.get_user_by_id(db=db, user_id=google_identity.user_id)
        if user is None:
            raise LookupError(f"Google identity {google_identity.id} has no User")
        user_service.fill_empty_profile(
            user,
            first_name=claims.given_name,
            last_name=claims.family_name,
            display_name=claims.name,
        )
        google_identity.profile_json = dict(claims.profile)
        await db.flush()
        return user

    user = await user_service.resolve_user_by_verified_email(
        db,
        claims.email,
        first_name=claims.given_name,
        last_name=claims.family_name,
        display_name=claims.name,
    )
    db.add(
        GoogleIdentity(
            user_id=user.id,
            subject=claims.subject,
            profile_json=dict(claims.profile),
        )
    )
    await db.flush()
    return user
