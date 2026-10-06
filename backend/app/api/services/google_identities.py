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
    query = select(GoogleIdentity).where(GoogleIdentity.subject == subject)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def resolve_user(db: AsyncSession, claims: GoogleClaims) -> User:
    """
    A linked Google account reaches its User whatever its email is now; otherwise the
    User is found or created by verified email and linked. Flushes, never commits.
    """
    google_identity = await get_google_identity(db=db, subject=claims.subject)
    if google_identity is not None:
        # The foreign key cascades on delete, so a Google identity always has its User.
        user = await user_service.get_user_by_id(db=db, user_id=google_identity.user_id)
        if user is None:
            raise LookupError(f"Google identity {google_identity.id} has no User")
        user_service.fill_empty_profile(user, _name_hints(claims))
        google_identity.profile_json = dict(claims.profile)
        await db.flush()
        return user

    user = await user_service.resolve_user_by_verified_email(db, claims.email, _name_hints(claims))
    db.add(
        GoogleIdentity(
            user_id=user.id,
            subject=claims.subject,
            profile_json=dict(claims.profile),
        )
    )
    await db.flush()
    return user


def _name_hints(claims: GoogleClaims) -> user_service.NameHints:
    return user_service.NameHints(
        first_name=claims.given_name,
        last_name=claims.family_name,
        display_name=claims.name,
    )
