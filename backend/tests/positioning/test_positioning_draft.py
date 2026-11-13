"""`POST /positioning/draft`: a draft of the User's Positioning from their X profile and posts."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.core.config import settings
from pumpkit.core.llm import FakeLLM, LLMError, get_llm
from pumpkit.core.llm_client import LLMNotConfiguredError
from pumpkit.main import app
from pumpkit.positioning import mediator
from pumpkit.positioning.draft_prompt import DRAFT_PROMPT
from tests.positioning.positioning import DRAFT, DRAFTED, POSITIONING, TEXT

USAGE = "/api/v1/usage"
NO_X_READ = "We couldn't read your X profile. Write it yourself, a few sentences is enough."
NO_MODEL = "We couldn't draft your positioning. Write it yourself, a few sentences is enough."


def _post(number: int, text: str) -> FetchedPost:
    """A post made `number` minutes after noon, so a higher number is a newer post."""
    posted_at = datetime(2026, 10, 9, 12, tzinfo=timezone.utc) + timedelta(minutes=number)
    return FetchedPost(post_id=str(number), text=text, posted_at=posted_at)


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


async def test_a_draft_answers_with_the_models_text_and_saves_nothing(client, on_x, fake_llm):
    fake_llm.replies = [{"positioning": DRAFTED}]

    response = await client.post(DRAFT)

    assert response.status_code == 200
    assert response.json() == {"text": DRAFTED, "reason": None, "can_draft": True}
    assert (await client.get(POSITIONING)).json()["text"] is None


async def test_a_draft_leaves_the_saved_positioning_alone(client, on_x, fake_llm):
    await client.put(POSITIONING, json={"text": TEXT})
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(DRAFT)

    assert (await client.get(POSITIONING)).json()["text"] == TEXT


async def test_the_model_is_asked_once_with_the_profile_and_the_newest_posts(
    client, on_x, fake_llm, fake_x_reader, fake_x_publisher
):
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(DRAFT)

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


async def test_a_user_who_renamed_their_x_account_gets_a_draft_from_their_own_posts(
    client, on_x, fake_llm, fake_x_reader, fake_x_publisher
):
    # @ada became @ada_builds on X since she signed in, and someone else took @ada.
    fake_x_reader.user_ids[fake_x_publisher.account.user_id] = "ada_builds"
    fake_x_reader.posts["ada_builds"] = fake_x_reader.posts["ada"]
    fake_x_reader.posts["ada"] = [_post(3, "A stranger's post.")]
    fake_llm.replies = [{"positioning": DRAFTED}]

    response = await client.post(DRAFT)

    assert response.json()["text"] == DRAFTED
    content = fake_llm.calls[0].messages[1]["content"]
    assert "Handle: @ada_builds\n" in content
    assert "Shipped usage-based pricing today." in content
    assert "A stranger's post." not in content


async def test_the_draft_call_uses_its_own_model_setting(client, on_x, fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "LLM_POSITIONING_MODEL", "local/positioning")
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(DRAFT)

    assert fake_llm.calls[0].model == "local/positioning"


async def test_only_the_20_newest_posts_reach_the_model(client, on_x, fake_llm, fake_x_reader):
    fake_x_reader.posts["ada"] = [_post(number, f"Post {number}.") for number in range(1, 26)]
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(DRAFT)

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

    await client.post(DRAFT)

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

    response = await client.post(DRAFT)

    assert response.json()["text"] == DRAFTED
    assert fake_llm.calls[0].messages[1]["content"] == (
        "<profile>\n"
        "Handle: @ada\n"
        "Bio: Solo founder. Building a pricing tool in public.\n"
        "Location: Lisbon\n"
        "Website: https://ada.dev\n"
        "</profile>"
    )


async def test_an_empty_profile_with_no_posts_gives_no_draft_and_asks_no_model(
    client, on_x, fake_llm, fake_x_publisher, fake_x_reader, connect_x
):
    fake_x_publisher.account = replace(
        fake_x_publisher.account, bio=None, location=None, website=None
    )
    await connect_x()
    fake_x_reader.posts["ada"] = []

    response = await client.post(DRAFT)

    assert response.status_code == 200
    assert response.json() == {
        "text": None,
        "reason": (
            "Your X profile has nothing to draft from yet. "
            "Write it yourself, a few sentences is enough."
        ),
        "can_draft": True,
    }
    assert fake_llm.calls == []


async def test_a_failed_x_read_gives_no_draft_and_a_reason(client, on_x, fake_llm, fake_x_reader):
    fake_x_reader.fail = True

    response = await client.post(DRAFT)

    assert response.status_code == 200
    assert response.json() == {"text": None, "reason": NO_X_READ, "can_draft": True}
    assert fake_llm.calls == []


async def test_an_account_x_no_longer_has_gives_no_draft_and_a_reason(
    client, on_x, fake_llm, fake_x_reader
):
    fake_x_reader.user_ids.clear()

    response = await client.post(DRAFT)

    assert response.json() == {"text": None, "reason": NO_X_READ, "can_draft": True}


async def test_a_user_with_no_x_connection_gets_no_draft_and_x_is_not_read(
    client, subscribed, fake_llm, fake_x_reader
):
    response = await client.post(DRAFT)

    assert response.status_code == 200
    assert response.json() == {"text": None, "reason": NO_X_READ, "can_draft": True}
    assert fake_x_reader.user_id_calls == []
    assert fake_llm.calls == []


@pytest.mark.parametrize(
    "failure", [LLMError("gpt-6-luna: APIConnectionError: down"), LLMNotConfiguredError("no key")]
)
async def test_a_failed_model_call_gives_no_draft_and_a_reason(client, on_x, fake_llm, failure):
    fake_llm.replies = [failure]

    response = await client.post(DRAFT)

    assert response.status_code == 200
    assert response.json() == {"text": None, "reason": NO_MODEL, "can_draft": True}


async def test_a_blank_answer_from_the_model_gives_no_draft(client, on_x, fake_llm):
    fake_llm.replies = [{"positioning": " \n\x00 "}]

    response = await client.post(DRAFT)

    assert response.json() == {"text": None, "reason": NO_MODEL, "can_draft": True}


async def test_the_draft_comes_back_trimmed_and_without_what_postgres_cannot_store(
    client, on_x, fake_llm
):
    fake_llm.replies = [{"positioning": "\n I post about\x00 pricing\ud800. \n"}]

    response = await client.post(DRAFT)

    assert response.json()["text"] == "I post about pricing."


async def test_a_draft_longer_than_a_positioning_can_be_is_cut_to_fit(client, on_x, fake_llm):
    fake_llm.replies = [{"positioning": "a" * 4001}]

    response = await client.post(DRAFT)

    assert response.json()["text"] == "a" * 4000


async def test_posts_reach_the_model_without_nuls_or_unpaired_surrogates(
    client, on_x, fake_llm, fake_x_reader
):
    fake_x_reader.posts["ada"] = [_post(1, "Raised\x00 my prices\ud83d.")]
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(DRAFT)

    assert "<post>\nRaised my prices.\n</post>" in fake_llm.calls[0].messages[1]["content"]


async def test_a_long_post_reaches_the_model_cut_to_1000_characters(
    client, on_x, fake_llm, fake_x_reader
):
    fake_x_reader.posts["ada"] = [_post(1, "a" * 999 + "bc")]
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(DRAFT)

    content = fake_llm.calls[0].messages[1]["content"]
    assert f"<post>\n{'a' * 999}b\n</post>" in content


async def test_the_models_answer_is_capped_at_4000_tokens(client, on_x, fake_llm):
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(DRAFT)

    assert fake_llm.calls[0].max_tokens == 4000


async def test_a_model_call_that_runs_too_long_gives_no_draft_and_a_reason(
    client, on_x, monkeypatch
):
    class NeverAnswers(FakeLLM):
        async def structured(self, **call):
            await asyncio.sleep(3600)
            return await super().structured(**call)

    app.dependency_overrides[get_llm] = lambda: NeverAnswers()
    monkeypatch.setattr(mediator, "DRAFT_CALL_SECONDS", 0.01)

    response = await client.post(DRAFT)

    assert response.status_code == 200
    assert response.json() == {"text": None, "reason": NO_MODEL, "can_draft": True}


async def test_a_draft_is_not_a_generation(client, on_x, fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "GENERATIONS_MONTHLY_CAP", 500)
    before = (await client.get(USAGE)).json()
    fake_llm.replies = [{"positioning": DRAFTED}]

    await client.post(DRAFT)

    assert (await client.get(USAGE)).json() == before


async def test_a_user_gets_5_drafts_a_day(client, on_x, fake_llm, fake_x_reader, fixed_clock):
    fake_llm.replies = [{"positioning": DRAFTED}] * 5
    for _ in range(4):
        fixed_clock.advance(timedelta(minutes=1))
        assert (await client.post(DRAFT)).json()["can_draft"] is True
    fixed_clock.advance(timedelta(minutes=1))

    fifth = await client.post(DRAFT)

    assert fifth.json() == {"text": DRAFTED, "reason": None, "can_draft": False}
    assert (await client.get(POSITIONING)).json()["can_draft"] is False

    sixth = await client.post(DRAFT)

    assert sixth.status_code == 429
    # The first draft was asked for at 12:01:30, so it stops counting a day later.
    assert sixth.json() == {
        "detail": "You can draft again tomorrow.",
        "retry_at": "2026-10-11T12:01:30Z",
    }
    assert len(fake_x_reader.user_id_calls) == 5
    assert len(fake_llm.calls) == 5


async def test_a_draft_is_allowed_again_a_day_after_the_first_of_the_5(
    client, on_x, fake_llm, fixed_clock
):
    fake_llm.replies = [{"positioning": DRAFTED}] * 6
    for _ in range(5):
        await client.post(DRAFT)
    fixed_clock.advance(timedelta(days=1))

    assert (await client.get(POSITIONING)).json()["can_draft"] is True
    again = await client.post(DRAFT)

    assert again.status_code == 200
    assert again.json()["text"] == DRAFTED


async def test_a_draft_that_read_x_and_failed_counts_towards_the_5(
    client, on_x, fake_llm, fake_x_reader
):
    fake_x_reader.fail = True
    for _ in range(5):
        await client.post(DRAFT)

    assert (await client.post(DRAFT)).status_code == 429


async def test_a_request_that_never_read_x_does_not_count(client, subscribed, fake_x_reader):
    for _ in range(6):
        assert (await client.post(DRAFT)).status_code == 200

    assert (await client.get(POSITIONING)).json()["can_draft"] is True


async def test_without_a_twitterapi_io_key_x_is_not_read_and_no_draft_is_used(
    client, on_x, fake_llm, fake_x_reader
):
    fake_x_reader.not_configured = True

    for _ in range(6):
        response = await client.post(DRAFT)
        assert response.status_code == 200
        assert response.json() == {"text": None, "reason": NO_X_READ, "can_draft": True}

    assert fake_x_reader.user_id_calls == []
    assert fake_llm.calls == []


async def test_without_an_llm_key_x_is_not_read_and_no_draft_is_used(
    client, on_x, fake_llm, fake_x_reader
):
    fake_llm.configured = False

    for _ in range(6):
        response = await client.post(DRAFT)
        assert response.status_code == 200
        assert response.json() == {"text": None, "reason": NO_MODEL, "can_draft": True}

    assert fake_x_reader.user_id_calls == []
    assert fake_llm.calls == []


async def test_each_user_has_their_own_5_drafts(
    client, on_x, fake_llm, sign_in_as_another_subscribed_user
):
    fake_llm.replies = [{"positioning": DRAFTED}] * 5
    for _ in range(5):
        await client.post(DRAFT)

    await sign_in_as_another_subscribed_user()

    assert (await client.get(POSITIONING)).json()["can_draft"] is True
    assert (await client.post(DRAFT)).status_code == 200
