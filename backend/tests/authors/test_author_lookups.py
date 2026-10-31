"""Adding a handle not in the Author directory: the lookup on X, its miss memory and its limits."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

import pytest

from pumpkit.authors.models import (
    MISS_MISSING,
    SOURCE_SEED,
    AuthorDirectoryEntry,
    AuthorFetch,
    AuthorHandleMiss,
    AuthorPost,
)
from pumpkit.authors.x_reader import (
    FakeXReader,
    FetchedPost,
    FetchedProfile,
    RecentPosts,
    get_x_reader,
)
from pumpkit.core.config import settings
from pumpkit.main import app

AUTHORS = "/api/v1/inspiration-authors"
DIRECTORY = "/api/v1/author-directory"

PHOTO = "https://pbs.twimg.com/profile_images/1/levelsio_normal.jpg"
NEW_PHOTO = "https://pbs.twimg.com/profile_images/2/levelsio_normal.jpg"
HANDLE_LIMIT = "You've looked up a lot of handles. Try again in {} minutes."
INSTANCE_PAUSED = (
    "Looking up new handles is paused for today. Pick from the suggestions or try again tomorrow."
)


def _posts(*ids: str) -> list[FetchedPost]:
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return [
        FetchedPost(post_id=post_id, text=f"post {post_id}", posted_at=start - timedelta(hours=i))
        for i, post_id in enumerate(ids)
    ]


async def _seed(db, handle: str, *, name: str = "Seeded", photo_url: str = PHOTO) -> None:
    db.add(
        AuthorDirectoryEntry(
            handle=handle,
            name=name,
            photo_url=photo_url,
            added_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
            source=SOURCE_SEED,
        )
    )
    await db.commit()


async def _directory(client) -> dict[str, dict]:
    return {entry["handle"]: entry for entry in (await client.get(DIRECTORY)).json()["data"]}


async def _miss(client, count: int, prefix: str = "nobody") -> None:
    """`count` lookups of distinct handles X doesn't know."""
    for i in range(count):
        response = await client.post(AUTHORS, json={"handle": f"{prefix}{i}"})
        assert response.status_code == 404


async def test_a_handle_in_the_directory_is_added_without_a_lookup(
    client, db, subscribed, fake_x_reader
):
    await _seed(db, "levelsio")
    fake_x_reader.posts["levelsio"] = _posts("1")

    response = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert response.status_code == 201
    assert fake_x_reader.profile_calls == []
    assert fake_x_reader.calls == ["levelsio"]


async def test_a_handle_not_in_the_directory_is_looked_up_once_and_joins_it_for_good(
    client, subscribed, fake_x_reader
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    fake_x_reader.profiles["levelsio"] = FetchedProfile(
        handle="levelsio", name="Pieter Levels", photo_url=PHOTO, protected=False
    )

    added = await client.post(AUTHORS, json={"handle": "levelsio"})
    await client.delete(f"{AUTHORS}/levelsio")

    assert added.status_code == 201
    assert (added.json()["name"], added.json()["photo_url"]) == ("Pieter Levels", PHOTO)
    assert fake_x_reader.profile_calls == ["levelsio"]
    assert (await _directory(client))["levelsio"] == {
        "handle": "levelsio",
        "name": "Pieter Levels",
        "photo_url": PHOTO,
        "persona_count": 0,
    }


async def test_a_found_account_without_posts_of_its_own_stays_in_the_directory(
    client, subscribed, fake_x_reader
):
    fake_x_reader.posts["replyguy"] = []

    response = await client.post(AUTHORS, json={"handle": "replyguy"})

    assert response.status_code == 422
    assert response.json()["detail"] == "@replyguy has no posts of its own to learn from."
    assert "replyguy" in await _directory(client)


async def test_a_found_account_without_posts_is_answered_from_its_fetch_within_the_reuse_window(
    client, subscribed, fake_x_reader, clock
):
    fake_x_reader.posts["replyguy"] = []

    first = await client.post(AUTHORS, json={"handle": "replyguy"})
    clock.advance(timedelta(days=settings.AUTHOR_POSTS_REUSE_DAYS) - timedelta(seconds=1))
    again = await client.post(AUTHORS, json={"handle": "replyguy"})

    assert first.status_code == again.status_code == 422
    assert (
        first.json()
        == again.json()
        == {
            "detail": "@replyguy has no posts of its own to learn from.",
            "code": "HANDLE_HAS_NO_POSTS",
        }
    )
    assert fake_x_reader.profile_calls == ["replyguy"]
    assert fake_x_reader.calls == ["replyguy"]


async def test_a_found_account_s_profile_name_stays_when_its_posts_carry_none(
    client, subscribed, fake_x_reader
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    fake_x_reader.profiles["levelsio"] = FetchedProfile(
        handle="levelsio", name="Pieter Levels", photo_url=PHOTO, protected=False
    )

    added = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert added.json()["name"] == "Pieter Levels"


async def test_a_fetch_updates_a_seeded_entry_s_photo_but_keeps_its_curated_name(
    client, db, subscribed, fake_x_reader, clock
):
    await _seed(db, "levelsio", name="Pieter Levels")
    fake_x_reader.posts["levelsio"] = _posts("1")
    fake_x_reader.names["levelsio"] = "levels.io 🌍"
    fake_x_reader.photos["levelsio"] = NEW_PHOTO

    added = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert (added.json()["name"], added.json()["photo_url"]) == ("Pieter Levels", NEW_PHOTO)
    clock.advance(timedelta(days=1))
    fake_x_reader.photos["levelsio"] = PHOTO
    refreshed = await client.post(f"{AUTHORS}/levelsio/refresh")
    assert (refreshed.json()["name"], refreshed.json()["photo_url"]) == ("Pieter Levels", PHOTO)


@pytest.mark.parametrize("suspended", [False, True])
async def test_a_handle_that_isnt_on_x_is_remembered_for_a_week(
    client, subscribed, fake_x_reader, clock, sign_in_as_another_subscribed_user, suspended
):
    if suspended:
        fake_x_reader.suspended.add("gone")

    first = await client.post(AUTHORS, json={"handle": "gone"})
    await sign_in_as_another_subscribed_user()
    clock.advance(timedelta(days=7, seconds=-1))
    remembered = await client.post(AUTHORS, json={"handle": "@Gone"})

    assert first.status_code == remembered.status_code == 404
    assert (
        first.json()
        == remembered.json()
        == {
            "detail": "@gone isn't on X.",
            "code": "HANDLE_NOT_ON_X",
        }
    )
    assert fake_x_reader.profile_calls == ["gone"]
    clock.advance(timedelta(seconds=1))
    assert (await client.post(AUTHORS, json={"handle": "gone"})).status_code == 404
    assert fake_x_reader.profile_calls == ["gone", "gone"]
    assert "gone" not in await _directory(client)


async def test_a_private_account_is_remembered_for_a_day_and_then_looked_up_again(
    client, subscribed, fake_x_reader, clock
):
    fake_x_reader.profiles["shy"] = FetchedProfile(
        handle="shy", name="Shy", photo_url=None, protected=True
    )

    first = await client.post(AUTHORS, json={"handle": "shy"})
    clock.advance(timedelta(days=1, seconds=-1))
    remembered = await client.post(AUTHORS, json={"handle": "shy"})

    assert first.status_code == remembered.status_code == 422
    assert (
        first.json()
        == remembered.json()
        == {
            "detail": "@shy is private, so Pumpkit can't read its posts.",
            "code": "HANDLE_PRIVATE",
        }
    )
    assert fake_x_reader.profile_calls == ["shy"]
    assert "shy" not in await _directory(client)

    clock.advance(timedelta(seconds=1))
    fake_x_reader.profiles["shy"] = FetchedProfile(
        handle="shy", name="Shy", photo_url=None, protected=False
    )
    fake_x_reader.posts["shy"] = _posts("1")
    assert (await client.post(AUTHORS, json={"handle": "shy"})).status_code == 201
    assert fake_x_reader.profile_calls == ["shy", "shy"]


async def test_the_duplicate_and_fourth_author_checks_come_before_any_lookup(
    client, subscribed, fake_x_reader
):
    for handle in ["a", "b", "c"]:
        fake_x_reader.posts[handle] = _posts(f"{handle}1")
        await client.post(AUTHORS, json={"handle": handle})

    duplicate = await client.post(AUTHORS, json={"handle": "a"})
    fourth = await client.post(AUTHORS, json={"handle": "unknown"})

    assert duplicate.status_code == fourth.status_code == 409
    assert fake_x_reader.profile_calls == ["a", "b", "c"]


async def test_over_the_hourly_limit_a_lookup_answers_when_the_oldest_leaves_the_hour(
    client, subscribed, fake_x_reader, clock
):
    await _miss(client, 1, prefix="early")
    clock.advance(timedelta(minutes=20))
    await _miss(client, 9)

    response = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert response.status_code == 429
    assert response.json()["detail"] == HANDLE_LIMIT.format(40)
    assert response.headers["Retry-After"] == str(40 * 60)
    assert len(fake_x_reader.profile_calls) == 10
    clock.advance(timedelta(minutes=40))
    assert (await client.post(AUTHORS, json={"handle": "late"})).status_code == 404


async def test_a_wait_of_part_of_a_minute_rounds_up(client, subscribed, fake_x_reader, clock):
    await _miss(client, 10)
    clock.advance(timedelta(minutes=59, seconds=30))

    response = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert response.json()["detail"] == "You've looked up a lot of handles. Try again in 1 minute."


async def test_over_the_daily_limit_a_lookup_answers_when_the_oldest_leaves_the_day(
    client, subscribed, fake_x_reader, clock, monkeypatch
):
    # Lowered, so the test stays under the per-minute limit on the route itself.
    monkeypatch.setattr(settings, "AUTHOR_LOOKUP_HOURLY_LIMIT", 2)
    monkeypatch.setattr(settings, "AUTHOR_LOOKUP_DAILY_LIMIT", 3)
    await _miss(client, 2, prefix="first")
    clock.advance(timedelta(hours=1))
    await _miss(client, 1, prefix="second")
    clock.advance(timedelta(hours=1))

    response = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert response.status_code == 429
    assert response.json()["detail"] == HANDLE_LIMIT.format(22 * 60)
    assert len(fake_x_reader.profile_calls) == 3


async def test_the_limits_are_per_user(
    client, subscribed, fake_x_reader, sign_in_as_another_subscribed_user
):
    await _miss(client, 10)
    await sign_in_as_another_subscribed_user()

    response = await client.post(AUTHORS, json={"handle": "other"})

    assert response.status_code == 404


async def test_over_the_instance_s_daily_cap_lookups_pause_for_everyone(
    client, subscribed, fake_x_reader, clock, monkeypatch, sign_in_as_another_subscribed_user
):
    monkeypatch.setattr(settings, "AUTHOR_LOOKUP_INSTANCE_DAILY_LIMIT", 3)
    await _miss(client, 2)
    await sign_in_as_another_subscribed_user()
    await _miss(client, 1, prefix="bob")

    response = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert response.status_code == 429
    assert response.json()["detail"] == INSTANCE_PAUSED
    assert len(fake_x_reader.profile_calls) == 3
    clock.advance(timedelta(days=1))
    assert (await client.post(AUTHORS, json={"handle": "late"})).status_code == 404


async def test_directory_picks_and_remembered_misses_never_count_towards_a_limit(
    client, db, subscribed, fake_x_reader, monkeypatch
):
    monkeypatch.setattr(settings, "AUTHOR_LOOKUP_HOURLY_LIMIT", 1)
    await _seed(db, "levelsio")
    await _seed(db, "paulg")
    fake_x_reader.posts["levelsio"] = _posts("1")
    fake_x_reader.posts["paulg"] = _posts("2")

    assert (await client.post(AUTHORS, json={"handle": "levelsio"})).status_code == 201
    assert (await client.post(AUTHORS, json={"handle": "gone"})).status_code == 404
    assert (await client.post(AUTHORS, json={"handle": "gone"})).status_code == 404
    assert (await client.post(AUTHORS, json={"handle": "paulg"})).status_code == 201
    assert (await client.post(AUTHORS, json={"handle": "new"})).status_code == 429
    assert fake_x_reader.profile_calls == ["gone"]


async def test_an_add_reuses_posts_any_user_fetched_within_a_week(
    client, subscribed, fake_x_reader, clock, sign_in_as_another_subscribed_user
):
    fake_x_reader.posts["levelsio"] = _posts("1")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    fake_x_reader.posts["levelsio"] = _posts("2", "1")
    clock.advance(timedelta(days=7, seconds=-1))
    await sign_in_as_another_subscribed_user()

    reused = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert reused.json()["post_count"] == 1
    assert fake_x_reader.calls == ["levelsio"]
    clock.advance(timedelta(seconds=1))
    await sign_in_as_another_subscribed_user("carol@example.com")
    refetched = await client.post(AUTHORS, json={"handle": "levelsio"})
    assert refetched.json()["post_count"] == 2
    assert fake_x_reader.calls == ["levelsio", "levelsio"]


async def test_a_refresh_keeps_its_daily_cooldown_and_is_not_a_lookup(
    client, subscribed, fake_x_reader, clock, monkeypatch
):
    monkeypatch.setattr(settings, "AUTHOR_LOOKUP_HOURLY_LIMIT", 1)
    fake_x_reader.posts["levelsio"] = _posts("1")
    await client.post(AUTHORS, json={"handle": "levelsio"})
    clock.advance(timedelta(days=1))

    refreshed = await client.post(f"{AUTHORS}/levelsio/refresh")

    assert refreshed.status_code == 200
    assert fake_x_reader.profile_calls == ["levelsio"]
    assert fake_x_reader.calls == ["levelsio", "levelsio"]


async def test_a_lookup_x_can_t_answer_is_not_remembered_or_counted(
    client, subscribed, fake_x_reader, assert_reported_502, monkeypatch
):
    monkeypatch.setattr(settings, "AUTHOR_LOOKUP_HOURLY_LIMIT", 1)
    fake_x_reader.fail = True

    assert_reported_502(await client.post(AUTHORS, json={"handle": "levelsio"}))

    fake_x_reader.fail = False
    fake_x_reader.posts["levelsio"] = _posts("1")
    assert (await client.post(AUTHORS, json={"handle": "levelsio"})).status_code == 201


@dataclass
class _AnsweredFirstElsewhere(FakeXReader):
    """X, where a concurrent add of the same handle stores its answer during this lookup."""

    elsewhere: Optional[Callable[[], Awaitable[Any]]] = None

    async def look_up_profile(self, handle: str) -> FetchedProfile:
        if self.elsewhere is not None:
            elsewhere, self.elsewhere = self.elsewhere, None
            await elsewhere()
        return await super().look_up_profile(handle)


async def test_a_handle_another_user_s_lookup_added_meanwhile_is_still_added(
    client, db, subscribed
):
    reader = _AnsweredFirstElsewhere(posts={"levelsio": _posts("1")})
    reader.elsewhere = lambda: _seed(db, "levelsio")
    app.dependency_overrides[get_x_reader] = lambda: reader

    response = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert response.status_code == 201
    assert list(await _directory(client)) == ["levelsio"]


async def test_a_miss_another_user_s_lookup_remembered_meanwhile_is_still_refused(
    client, db, subscribed, clock
):
    async def remember_elsewhere() -> None:
        db.add(
            AuthorHandleMiss(
                handle="gone", reason=MISS_MISSING, remembered_until=clock() + timedelta(days=7)
            )
        )
        await db.commit()

    reader = _AnsweredFirstElsewhere()
    reader.elsewhere = remember_elsewhere
    app.dependency_overrides[get_x_reader] = lambda: reader

    first = await client.post(AUTHORS, json={"handle": "gone"})
    again = await client.post(AUTHORS, json={"handle": "gone"})

    assert first.status_code == again.status_code == 404
    assert reader.profile_calls == ["gone"]


@dataclass
class _FetchedFirstElsewhere(FakeXReader):
    """X, where a concurrent add of the same handle stores its posts during this fetch."""

    elsewhere: Optional[Callable[[], Awaitable[Any]]] = None

    async def fetch_recent_posts(self, handle: str) -> RecentPosts:
        if self.elsewhere is not None:
            elsewhere, self.elsewhere = self.elsewhere, None
            await elsewhere()
        return await super().fetch_recent_posts(handle)


@pytest.mark.parametrize("in_directory", [True, False])
async def test_a_handle_whose_posts_another_user_s_add_stored_meanwhile_is_still_added(
    client, db, subscribed, clock, in_directory
):
    posts = _posts("1", "2")

    async def store_elsewhere() -> None:
        db.add_all(
            AuthorPost(
                id=post.post_id,
                handle="levelsio",
                text=post.text,
                posted_at=post.posted_at,
                fetched_at=clock(),
            )
            for post in posts
        )
        db.add(AuthorFetch(handle="levelsio", last_fetched_at=clock()))
        await db.commit()

    if in_directory:
        await _seed(db, "levelsio")
    reader = _FetchedFirstElsewhere(posts={"levelsio": posts})
    reader.elsewhere = store_elsewhere
    app.dependency_overrides[get_x_reader] = lambda: reader

    response = await client.post(AUTHORS, json={"handle": "levelsio"})

    assert response.status_code == 201
    assert response.json()["post_count"] == 2
