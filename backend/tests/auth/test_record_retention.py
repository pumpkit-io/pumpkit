"""
Session and Magic link records are deleted 90 days after they expire, whenever a
Magic link is requested or a Session is created.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.google_sign_in import GoogleClaims
from pumpkit.auth.models import MagicLink, RefreshToken, User
from tests.conftest import magic_link_token


def _days_ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def _seed_records_expired(db: AsyncSession, user: User, *, days_ago: int) -> None:
    """One Magic link and one refresh token that expired `days_ago` days ago."""
    expired_at = _days_ago(days_ago)
    issued_at = expired_at - timedelta(days=7)
    db.add(
        MagicLink(
            email=f"expired-{days_ago}@example.com",
            token_hash=f"magic-link-expired-{days_ago}",
            sent_at=issued_at,
            expires_at=expired_at,
            requester_ip="203.0.113.7",
            requester_user_agent="Old browser",
        )
    )
    db.add(
        RefreshToken(
            user_id=user.id,
            sign_in_method="magic_link",
            session_id=f"session-expired-{days_ago}",
            refresh_token_hash=f"refresh-token-expired-{days_ago}",
            created_at=issued_at,
            expires_at=expired_at,
            ip="203.0.113.7",
            user_agent="Old browser",
        )
    )
    await db.commit()


async def _stored_magic_link_hashes(db: AsyncSession) -> set[str]:
    await db.commit()
    return set((await db.execute(select(MagicLink.token_hash))).scalars())


async def _stored_refresh_token_hashes(db: AsyncSession) -> set[str]:
    await db.commit()
    return set((await db.execute(select(RefreshToken.refresh_token_hash))).scalars())


async def test_requesting_a_magic_link_deletes_records_expired_over_90_days_ago(client, db, user):
    await _seed_records_expired(db, user, days_ago=91)
    await _seed_records_expired(db, user, days_ago=89)

    response = await client.post(
        "/api/v1/login/magic-link/request", json={"email": "bob@example.com"}
    )

    assert response.status_code == 200
    magic_links = await _stored_magic_link_hashes(db)
    assert "magic-link-expired-91" not in magic_links
    assert "magic-link-expired-89" in magic_links
    assert len(magic_links) == 2  # The link just requested is kept too
    assert await _stored_refresh_token_hashes(db) == {"refresh-token-expired-89"}


async def test_google_sign_in_deletes_records_expired_over_90_days_ago(
    new_browser, sign_in_with_google, db, user
):
    await _seed_records_expired(db, user, days_ago=91)
    await _seed_records_expired(db, user, days_ago=89)

    landed = await sign_in_with_google(
        new_browser(), GoogleClaims(subject="google-sub-alice", email=user.email)
    )

    assert landed.status_code == 303
    assert await _stored_magic_link_hashes(db) == {"magic-link-expired-89"}
    refresh_tokens = await _stored_refresh_token_hashes(db)
    assert "refresh-token-expired-91" not in refresh_tokens
    assert "refresh-token-expired-89" in refresh_tokens
    assert len(refresh_tokens) == 2  # The new Session's refresh token is kept too


async def test_magic_link_sign_in_deletes_records_expired_over_90_days_ago(
    new_browser, auth_outbox, db, user
):
    browser = new_browser()
    requested = await browser.post("/api/v1/login/magic-link/request", json={"email": user.email})
    assert requested.status_code == 200
    # Seeded after the request, so only starting the Session can delete them.
    await _seed_records_expired(db, user, days_ago=91)
    await _seed_records_expired(db, user, days_ago=89)

    opened = await browser.get(
        "/api/v1/login/magic-link",
        params={"token": magic_link_token(auth_outbox.messages[-1].link_url)},
    )

    assert opened.status_code == 303
    assert opened.headers["location"].startswith("http://localhost:5173/auth/magic-link/callback#")
    magic_links = await _stored_magic_link_hashes(db)
    assert "magic-link-expired-91" not in magic_links
    assert "magic-link-expired-89" in magic_links
    refresh_tokens = await _stored_refresh_token_hashes(db)
    assert "refresh-token-expired-91" not in refresh_tokens
    assert "refresh-token-expired-89" in refresh_tokens


async def test_a_purged_refresh_token_is_refused_like_an_unknown_one(
    new_browser, sign_in_by_magic_link, db, user
):
    browser = new_browser()
    await sign_in_by_magic_link(browser, user.email)
    purged_cookie = browser.cookies["refresh_token"]
    token = (await db.execute(select(RefreshToken))).scalar_one()
    token.created_at = _days_ago(120)
    token.expires_at = _days_ago(91)
    await db.commit()

    await sign_in_by_magic_link(new_browser(), "bob@example.com")
    assert token.refresh_token_hash not in await _stored_refresh_token_hashes(db)

    browser.cookies.set("refresh_token", purged_cookie)
    refused = await browser.post("/api/v1/refresh-token")
    unknown_browser = new_browser()
    unknown_browser.cookies.set("refresh_token", "not-a-refresh-token")
    unknown = await unknown_browser.post("/api/v1/refresh-token")

    assert refused.status_code == unknown.status_code == 401
    assert refused.json() == unknown.json() == {"detail": "invalid_refresh_token"}
    assert refused.headers["WWW-Authenticate"] == unknown.headers["WWW-Authenticate"]
