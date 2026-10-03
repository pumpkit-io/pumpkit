from datetime import datetime, timedelta, timezone

import app.api.services.auth_sessions as auth_sessions_service
from app.core.security import hash_token
from app.db.models import AuthSession


async def _make_session(
    db, user, *, token: str, family_id: str, revoked: bool = False
) -> AuthSession:
    session = AuthSession(
        user_id=user.id,
        auth_method="magic_link",
        family_id=family_id,
        refresh_token_hash=hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        is_revoked=revoked,
    )
    db.add(session)
    await db.commit()
    return session


async def test_active_session_is_found(db, user):
    await _make_session(db, user, token="tok-active", family_id="fam-a")
    found = await auth_sessions_service.get_active_auth_session_by_hash(
        db=db, token_hash=hash_token("tok-active")
    )
    assert found is not None


async def test_revoked_session_is_not_returned(db, user):
    await _make_session(db, user, token="tok-revoked", family_id="fam-a", revoked=True)
    found = await auth_sessions_service.get_active_auth_session_by_hash(
        db=db, token_hash=hash_token("tok-revoked")
    )
    assert found is None


async def test_revoke_family_revokes_only_that_family(db, user):
    a = await _make_session(db, user, token="tok-1", family_id="fam-a")
    b = await _make_session(db, user, token="tok-2", family_id="fam-b")
    await auth_sessions_service.revoke_auth_session_family(db=db, family_id="fam-a")
    await db.refresh(a)
    await db.refresh(b)
    assert a.is_revoked is True
    assert a.revoked_at is not None
    assert b.is_revoked is False


async def test_revoke_all_user_sessions(db, user):
    a = await _make_session(db, user, token="tok-3", family_id="fam-a")
    b = await _make_session(db, user, token="tok-4", family_id="fam-b")
    await auth_sessions_service.revoke_all_user_auth_sessions(db=db, user_id=user.id)
    await db.refresh(a)
    await db.refresh(b)
    assert a.is_revoked is True
    assert b.is_revoked is True
