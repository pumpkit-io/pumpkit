"""
`POST /positioning/draft/start` drafts the User's Positioning from their X profile and posts in the
background, and `GET /positioning` answers with the draft until the User saves a Positioning.
"""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.core.config import settings
from pumpkit.core.llm import FakeLLM, LLMError, get_llm
from pumpkit.core.llm_client import LLMNotConfiguredError
from pumpkit.main import app
from pumpkit.positioning import mediator
from pumpkit.positioning.draft import PositioningDraft
from pumpkit.positioning.draft_prompt import DRAFT_PROMPT
from tests.positioning.positioning import (
    DRAFTED,
    POSITIONING,
    START_DRAFT,
    TEXT,
    positioning_draft,
)

USAGE = "/api/v1/usage"
NO_X_READ = "We couldn't read your X profile. Write it yourself, a few sentences is enough."
NO_MODEL = "We couldn't draft your positioning. Write it yourself, a few sentences is enough."
READY = {"state": "ready", "text": DRAFTED, "reason": None}


def _post(number: int, text: str) -> FetchedPost:
    """A post made `number` minutes after noon, so a higher number is a newer post."""
    posted_at = datetime(2026, 10, 9, 12, tzinfo=timezone.utc) + timedelta(minutes=number)
    return FetchedPost(post_id=str(number), text=text, posted_at=posted_at)


def _failed(reason: str) -> dict:
    return {"state": "failed", "text": None, "reason": reason}


@pytest.fixture
async def on_x(fake_x_publisher, fake_x_reader, connect_x, fixed_clock, subscribed):
    """Alice is Subscribed and connected to @ada, whose profile is filled in and who has posted."""
    fake_x_publisher.account = replace(
        fake_x_publisher.account,
        bio="Solo founder. Building a pricing tool in public.",
        location="Lisbon",
        website="https://ada.dev",
    )
    await connect_x()
    fake_x_reader.user_ids[fake_x_publisher.account.user_id] = "ada"
    fake_x_reader.posts["ada"] = [
        _post(1, "Raised my prices 20% and nobody left."),
        _post(2, "Shipped usage-based pricing today."),
    ]


async def _start(client) -> Any:
    """Start a draft, and answer with the draft `GET /positioning` reads once the task has run."""
    started = await client.post(START_DRAFT)
    assert started.status_code == 202, started.text
    return await positioning_draft(client)


async def test_a_user_with_no_draft_has_none_until_one_starts(client, on_x):
    response = await client.get(POSITIONING)

    assert response.json() == {"text": None, "saved_at": None, "draft": None}


async def test_a_started_draft_is_kept_ready_and_saves_no_positioning(client, on_x, fake_llm):
    fake_llm.replies = [{"positioning": DRAFTED}]

    started = await client.post(START_DRAFT)

    assert started.status_code == 202
    assert (await client.get(POSITIONING)).json() == {
        "text": None,
        "saved_at": None,
        "draft": READY,
    }


async def test_the_start_answers_before_the_draft_is_written_and_it_runs_meanwhile(
    client, on_x, background_tasks, fake_llm
):
    fake_llm.held["PositioningDraft"] = written = asyncio.Event()
    fake_llm.replies = [{"positioning": DRAFTED}]

    started = await client.post(START_DRAFT)

    assert started.status_code == 202
    assert await positioning_draft(client) == {"state": "running", "text": None, "reason": None}
    written.set()
    await background_tasks.wait()
    assert await positioning_draft(client) == READY


async def test_a_second_start_while_one_runs_starts_nothing(
    client, on_x, background_tasks, fake_llm, fake_x_reader
):
    fake_llm.held["PositioningDraft"] = written = asyncio.Event()
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(START_DRAFT)
    second = await client.post(START_DRAFT)
    written.set()
    await background_tasks.wait()

    assert second.status_code == 202
    assert len(fake_x_reader.user_id_calls) == 1
    assert await positioning_draft(client) == READY


async def test_a_ready_draft_is_kept_and_a_later_start_starts_nothing(
    client, on_x, fake_llm, fake_x_reader
):
    fake_llm.replies = [{"positioning": DRAFTED}]
    await client.post(START_DRAFT)

    assert await _start(client) == READY
    assert len(fake_x_reader.user_id_calls) == 1
    assert len(fake_llm.calls) == 1


async def test_a_failed_draft_is_tried_again_by_the_next_start(
    client, on_x, fake_llm, fake_x_reader
):
    fake_x_reader.fail = True
    assert await _start(client) == _failed(NO_X_READ)
    fake_x_reader.fail = False
    fake_llm.replies = [{"positioning": DRAFTED}]

    assert await _start(client) == READY


async def test_a_user_with_a_positioning_starts_no_draft_and_reads_none(
    client, on_x, fake_llm, fake_x_reader
):
    await client.put(POSITIONING, json={"text": TEXT})

    response = await client.post(START_DRAFT)

    assert response.status_code == 202
    assert fake_x_reader.user_id_calls == []
    assert fake_llm.calls == []
    assert (await client.get(POSITIONING)).json()["text"] == TEXT
    assert await positioning_draft(client) is None


async def test_saving_a_positioning_removes_the_draft(client, on_x, fake_llm, fake_x_reader):
    fake_llm.replies = [{"positioning": DRAFTED}]
    await client.post(START_DRAFT)

    await client.put(POSITIONING, json={"text": DRAFTED})

    assert (await client.get(POSITIONING)).json()["draft"] is None
    await client.post(START_DRAFT)
    assert len(fake_x_reader.user_id_calls) == 1


async def test_a_draft_that_ends_after_its_positioning_was_saved_records_nothing(
    client, on_x, background_tasks, fake_llm
):
    fake_llm.held["PositioningDraft"] = written = asyncio.Event()
    fake_llm.replies = [{"positioning": DRAFTED}]
    await client.post(START_DRAFT)

    await client.put(POSITIONING, json={"text": TEXT})
    written.set()
    await background_tasks.wait()

    assert (await client.get(POSITIONING)).json() == {
        "text": TEXT,
        "saved_at": "2026-10-10T12:00:30Z",
        "draft": None,
    }


async def test_a_draft_running_longer_than_its_calls_can_take_counts_as_failed(
    client, on_x, background_tasks, fixed_clock, fake_llm
):
    fake_llm.held["PositioningDraft"] = asyncio.Event()
    await client.post(START_DRAFT)
    fixed_clock.advance(timedelta(minutes=3, seconds=59))
    assert (await positioning_draft(client))["state"] == "running"

    fixed_clock.advance(timedelta(seconds=1))

    assert await positioning_draft(client) == _failed(NO_MODEL)


async def test_a_stale_draft_is_started_again_and_the_stuck_one_records_nothing(
    client, on_x, background_tasks, fixed_clock, fake_x_reader
):
    stuck = FakeLLM(replies=[{"positioning": "The stuck draft."}], latency=0.1)
    app.dependency_overrides[get_llm] = lambda: stuck
    await client.post(START_DRAFT)
    fixed_clock.advance(timedelta(minutes=4))
    app.dependency_overrides[get_llm] = lambda: FakeLLM(replies=[{"positioning": DRAFTED}])

    await client.post(START_DRAFT)
    await background_tasks.wait()

    assert len(fake_x_reader.user_id_calls) == 2
    assert await positioning_draft(client) == READY


async def test_the_model_is_asked_once_with_the_profile_and_the_newest_posts(
    client, on_x, fake_llm, fake_x_reader, fake_x_publisher
):
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(START_DRAFT)

    assert fake_x_reader.user_id_calls == [fake_x_publisher.account.user_id]
    assert len(fake_llm.calls) == 1
    call = fake_llm.calls[0]
    assert call.model == "openai/gpt-6-luna"
    assert call.messages == [
        {"role": "system", "content": DRAFT_PROMPT},
        {
            "role": "user",
            "content": (
                "<profile>\n"
                "Handle: @ada\n"
                "Bio: Solo founder. Building a pricing tool in public.\n"
                "Location: Lisbon\n"
                "Website: https://ada.dev\n"
                "</profile>\n"
                "\n"
                "<posts>\n"
                "<post>\nShipped usage-based pricing today.\n</post>\n"
                "<post>\nRaised my prices 20% and nobody left.\n</post>\n"
                "</posts>"
            ),
        },
    ]


def test_the_prompt_still_asks_for_three_to_five_sentences():
    assert "three to five" in DRAFT_PROMPT.lower()


async def test_a_user_who_renamed_their_x_account_gets_a_draft_from_their_own_posts(
    client, on_x, fake_llm, fake_x_reader, fake_x_publisher
):
    # @ada became @ada_builds on X since she signed in, and someone else took @ada.
    fake_x_reader.user_ids[fake_x_publisher.account.user_id] = "ada_builds"
    fake_x_reader.posts["ada_builds"] = fake_x_reader.posts["ada"]
    fake_x_reader.posts["ada"] = [_post(3, "A stranger's post.")]
    fake_llm.replies = [{"positioning": DRAFTED}]

    assert await _start(client) == READY
    content = fake_llm.calls[0].messages[1]["content"]
    assert "Handle: @ada_builds\n" in content
    assert "Shipped usage-based pricing today." in content
    assert "A stranger's post." not in content


async def test_the_draft_call_uses_its_own_model_setting(client, on_x, fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "LLM_POSITIONING_MODEL", "local/positioning")
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(START_DRAFT)

    assert fake_llm.calls[0].model == "local/positioning"


async def test_only_the_20_newest_posts_reach_the_model(client, on_x, fake_llm, fake_x_reader):
    fake_x_reader.posts["ada"] = [_post(number, f"Post {number}.") for number in range(1, 26)]
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(START_DRAFT)

    content = fake_llm.calls[0].messages[1]["content"]
    assert content.count("<post>") == 20
    assert "<post>\nPost 25.\n</post>\n<post>\nPost 24.\n</post>" in content
    assert "Post 5." not in content


async def test_a_profile_field_x_left_blank_is_left_out_of_what_the_model_reads(
    client, on_x, fake_llm, fake_x_publisher, connect_x
):
    fake_x_publisher.account = replace(fake_x_publisher.account, location=None, website=None)
    await connect_x()
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(START_DRAFT)

    assert (
        fake_llm.calls[0]
        .messages[1]["content"]
        .startswith(
            "<profile>\n"
            "Handle: @ada\n"
            "Bio: Solo founder. Building a pricing tool in public.\n"
            "</profile>\n"
        )
    )


async def test_a_user_with_a_bio_and_no_posts_gets_a_draft_from_the_bio(
    client, on_x, fake_llm, fake_x_reader
):
    fake_x_reader.posts["ada"] = []
    fake_llm.replies = [{"positioning": DRAFTED}]

    assert await _start(client) == READY
    assert fake_llm.calls[0].messages[1]["content"] == (
        "<profile>\n"
        "Handle: @ada\n"
        "Bio: Solo founder. Building a pricing tool in public.\n"
        "Location: Lisbon\n"
        "Website: https://ada.dev\n"
        "</profile>"
    )


async def test_an_empty_profile_with_no_posts_fails_with_a_reason_and_asks_no_model(
    client, on_x, fake_llm, fake_x_publisher, fake_x_reader, connect_x
):
    fake_x_publisher.account = replace(
        fake_x_publisher.account, bio=None, location=None, website=None
    )
    await connect_x()
    fake_x_reader.posts["ada"] = []

    assert await _start(client) == _failed(
        "Your X profile has nothing to draft from yet. "
        "Write it yourself, a few sentences is enough."
    )
    assert fake_llm.calls == []


async def test_a_failed_x_read_fails_with_a_reason(client, on_x, fake_llm, fake_x_reader):
    fake_x_reader.fail = True

    assert await _start(client) == _failed(NO_X_READ)
    assert fake_llm.calls == []


async def test_an_account_x_no_longer_has_fails_with_a_reason(client, on_x, fake_x_reader):
    fake_x_reader.user_ids.clear()

    assert await _start(client) == _failed(NO_X_READ)


async def test_a_user_with_no_x_connection_gets_a_failed_draft_and_x_is_not_read(
    client, subscribed, fake_llm, fake_x_reader
):
    assert await _start(client) == _failed(NO_X_READ)
    assert fake_x_reader.user_id_calls == []
    assert fake_llm.calls == []


@pytest.mark.parametrize(
    "failure", [LLMError("gpt-6-luna: APIConnectionError: down"), LLMNotConfiguredError("no key")]
)
async def test_a_failed_model_call_fails_with_a_reason(client, on_x, fake_llm, failure):
    fake_llm.replies = [failure]

    assert await _start(client) == _failed(NO_MODEL)


async def test_an_unexpected_error_in_the_draft_still_ends_it_failed(
    client, on_x, fake_llm, fake_x_reader
):
    fake_llm.replies = [RuntimeError("boom")]

    assert await _start(client) == _failed(NO_MODEL)


async def test_a_draft_cancelled_on_shutdown_ends_failed(client, on_x, background_tasks, fake_llm):
    fake_llm.held["PositioningDraft"] = asyncio.Event()
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(START_DRAFT)
    await background_tasks.cancel()

    assert await positioning_draft(client) == _failed(NO_MODEL)


async def test_a_blank_answer_from_the_model_fails_with_a_reason(client, on_x, fake_llm):
    fake_llm.replies = [{"positioning": " \n\x00 "}]

    assert await _start(client) == _failed(NO_MODEL)


async def test_the_draft_is_kept_trimmed_and_without_what_postgres_cannot_store(
    client, on_x, fake_llm
):
    fake_llm.replies = [{"positioning": "\n I post about\x00 pricing\ud800. \n"}]

    assert (await _start(client))["text"] == "I post about pricing."


async def test_a_draft_longer_than_a_positioning_can_be_is_cut_to_fit(client, on_x, fake_llm):
    fake_llm.replies = [{"positioning": "a" * 4001}]

    assert (await _start(client))["text"] == "a" * 4000


async def test_posts_reach_the_model_without_nuls_or_unpaired_surrogates(
    client, on_x, fake_llm, fake_x_reader
):
    fake_x_reader.posts["ada"] = [_post(1, "Raised\x00 my prices\ud83d.")]
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(START_DRAFT)

    assert "<post>\nRaised my prices.\n</post>" in fake_llm.calls[0].messages[1]["content"]


async def test_a_long_post_reaches_the_model_cut_to_1000_characters(
    client, on_x, fake_llm, fake_x_reader
):
    fake_x_reader.posts["ada"] = [_post(1, "a" * 999 + "bc")]
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(START_DRAFT)

    content = fake_llm.calls[0].messages[1]["content"]
    assert f"<post>\n{'a' * 999}b\n</post>" in content


async def test_the_models_answer_is_capped_at_4000_tokens(client, on_x, fake_llm):
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(START_DRAFT)

    assert fake_llm.calls[0].max_tokens == 4000


async def test_a_model_call_that_runs_too_long_fails_with_a_reason(client, on_x, monkeypatch):
    app.dependency_overrides[get_llm] = lambda: FakeLLM(latency=3600)
    monkeypatch.setattr(mediator, "DRAFT_CALL_SECONDS", 0.01)

    assert await _start(client) == _failed(NO_MODEL)


async def test_a_draft_that_waits_too_long_for_a_model_slot_fails_with_a_reason(
    client, on_x, background_tasks, fake_llm, monkeypatch
):
    monkeypatch.setattr(settings, "LLM_CALLS_IN_FLIGHT", 1)
    monkeypatch.setattr(mediator, "DRAFT_SLOT_WAIT_SECONDS", 0.01)
    monkeypatch.setattr(mediator, "DRAFT_CALL_SECONDS", 0.01)
    busy = FakeLLM(standing={"PositioningDraft": {"positioning": "Another call."}}, latency=3600)
    holding = asyncio.create_task(
        busy.structured(model="m", messages=[], response_model=PositioningDraft)
    )
    await asyncio.sleep(0)
    fake_llm.replies = [{"positioning": DRAFTED}]

    try:
        await client.post(START_DRAFT)
        await background_tasks.wait()
    finally:
        holding.cancel()

    assert await positioning_draft(client) == _failed(NO_MODEL)


async def test_a_draft_is_not_a_generation(client, on_x, fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 500)
    before = (await client.get(USAGE)).json()
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(START_DRAFT)

    assert (await client.get(USAGE)).json() == before


async def test_a_user_gets_5_draft_requests_a_day(
    client, on_x, fake_llm, fake_x_reader, fixed_clock
):
    fake_x_reader.fail = True
    for _ in range(5):
        fixed_clock.advance(timedelta(minutes=1))
        assert await _start(client) == _failed(NO_X_READ)
    fake_x_reader.fail = False
    fake_llm.replies = [{"positioning": DRAFTED}]

    # The sixth start says why it ran nothing, not why the last draft failed.
    assert await _start(client) == _failed(NO_MODEL)
    assert len(fake_x_reader.user_id_calls) == 5
    assert fake_llm.calls == []


async def test_a_draft_is_allowed_again_a_day_after_the_first_of_the_5(
    client, on_x, fake_llm, fake_x_reader, fixed_clock
):
    fake_x_reader.fail = True
    for _ in range(5):
        await client.post(START_DRAFT)
    fake_x_reader.fail = False
    fake_llm.replies = [{"positioning": DRAFTED}]
    fixed_clock.advance(timedelta(days=1))

    assert await _start(client) == READY


async def test_a_start_that_never_reads_x_does_not_count(
    client, subscribed, connect_x, fake_x_publisher, fake_x_reader, fake_llm
):
    for _ in range(6):
        assert await _start(client) == _failed(NO_X_READ)
    await connect_x()
    fake_x_reader.user_ids[fake_x_publisher.account.user_id] = "ada"
    fake_x_reader.posts["ada"] = [_post(1, "Shipped usage-based pricing today.")]
    fake_llm.replies = [{"positioning": DRAFTED}]

    assert (await _start(client))["state"] == "ready"


async def test_without_a_twitterapi_io_key_no_draft_starts_and_it_reads_as_failed(
    client, on_x, fake_llm, fake_x_reader
):
    fake_x_reader.not_configured = True

    for _ in range(6):
        assert await _start(client) == _failed(NO_X_READ)

    assert fake_x_reader.user_id_calls == []
    assert fake_llm.calls == []


async def test_without_an_llm_key_no_draft_starts_and_it_reads_as_failed(
    client, on_x, fake_llm, fake_x_reader
):
    fake_llm.configured = False

    for _ in range(6):
        assert await _start(client) == _failed(NO_MODEL)

    assert fake_x_reader.user_id_calls == []
    assert fake_llm.calls == []


async def test_each_user_has_their_own_draft(
    client, on_x, fake_llm, sign_in_as_another_subscribed_user
):
    fake_llm.replies = [{"positioning": DRAFTED}]
    await client.post(START_DRAFT)

    await sign_in_as_another_subscribed_user()

    assert await positioning_draft(client) is None


async def test_a_user_without_a_subscription_can_start_a_draft_but_not_save_it(
    client, connect_x, fake_x_publisher, fake_x_reader, fake_llm
):
    await connect_x()
    fake_x_reader.user_ids[fake_x_publisher.account.user_id] = "ada"
    fake_x_reader.posts["ada"] = [_post(1, "Shipped usage-based pricing today.")]
    fake_llm.replies = [{"positioning": DRAFTED}]

    started = await client.post(START_DRAFT)

    assert started.status_code == 202
    assert len(fake_llm.calls) == 1
    assert (await client.put(POSITIONING, json={"text": DRAFTED})).status_code == 403


async def test_a_signed_out_visitor_cannot_start_a_draft(new_browser):
    assert (await new_browser().post(START_DRAFT)).status_code == 401
