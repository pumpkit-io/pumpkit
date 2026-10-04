from datetime import datetime, timedelta, timezone

import app.api.services.refresh_tokens as refresh_tokens_service
from app.core.security import hash_token
from app.db.models import RefreshToken


async def _make_refresh_token(
    db, user, *, token: str, session_id: str, revoked: bool = False
) -> RefreshToken:
    refresh_token = RefreshToken(
        user_id=user.id,
        sign_in_method="magic_link",
        session_id=session_id,
        refresh_token_hash=hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        is_revoked=revoked,
    )
    db.add(refresh_token)
    await db.commit()
    return refresh_token


async def test_active_refresh_token_is_found(db, user):
    await _make_refresh_token(db, user, token="tok-active", session_id="session-a")
    found = await refresh_tokens_service.get_active_refresh_token_by_hash(
        db=db, token_hash=hash_token("tok-active")
    )
    assert found is not None


async def test_revoked_refresh_token_is_not_returned(db, user):
    await _make_refresh_token(db, user, token="tok-revoked", session_id="session-a", revoked=True)
    found = await refresh_tokens_service.get_active_refresh_token_by_hash(
        db=db, token_hash=hash_token("tok-revoked")
    )
    assert found is None


async def test_revoke_session_revokes_only_that_session(db, user):
    a = await _make_refresh_token(db, user, token="tok-1", session_id="session-a")
    b = await _make_refresh_token(db, user, token="tok-2", session_id="session-b")
    await refresh_tokens_service.revoke_session(db=db, session_id="session-a")
    await db.refresh(a)
    await db.refresh(b)
    assert a.is_revoked is True
    assert a.revoked_at is not None
    assert b.is_revoked is False


async def test_revoke_all_user_sessions(db, user):
    a = await _make_refresh_token(db, user, token="tok-3", session_id="session-a")
    b = await _make_refresh_token(db, user, token="tok-4", session_id="session-b")
    await refresh_tokens_service.revoke_all_user_sessions(db=db, user_id=user.id)
    await db.refresh(a)
    await db.refresh(b)
    assert a.is_revoked is True
    assert b.is_revoked is True
