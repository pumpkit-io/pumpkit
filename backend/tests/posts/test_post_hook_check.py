"""The Jev check and the hook call on Feedback Versions, seen through the Posts API, the scripted model and Jev."""

import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.core.classifier import ChoiceAnswer, ClassifierError, JevClassifier, get_classifier
from pumpkit.core.config import settings
from pumpkit.main import app
from pumpkit.posts.models import Post
from pumpkit.posts.writing.prompts.draft_post import DRAFT_POST_PROMPT
from pumpkit.posts.writing.prompts.hook import HOOK_PROMPT
from tests.posts.hook_replies import no_hook

AUTHORS = "/api/v1/inspiration-authors"
POSTS = "/api/v1/posts"
DEFAULT_MODEL = "openai/gpt-5.6-luna"

HOOK = "I ship one tiny thing a week."
DRAFT_2 = f"{HOOK}\n\nshipping small beats shipping big"

LEVELSIO_CORPUS = (
    "Below are real posts by the writers whose voice you are reproducing, grouped by author. "
    "They are examples of HOW to write, never of what to write about.\n\n"
    '<creator handle="levelsio">\n'
    "<post>levelsio post 0</post>\n"
    "</creator>"
)


def _versions_url(post_id: str) -> str:
    return f"{POSTS}/{post_id}/versions"


@pytest.fixture
async def post_id(client, subscribed, fake_x_reader, fake_llm) -> str:
    """A Post from the Brief "ship small things" whose first Version's Final is "final 1"."""
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post 0",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc) - timedelta(hours=1),
        )
    ]
    assert (await client.post(AUTHORS, json={"handle": "levelsio"})).status_code == 201
    fake_llm.replies = [no_hook(), {"post": "draft 1"}, {"post": "final 1"}]
    response = await client.post(POSTS, json={"brief": "ship small things"})
    assert response.status_code == 201, response.text
    fake_llm.calls.clear()
    return response.json()["id"]


def _answer(choice: str) -> dict[str, ChoiceAnswer]:
    probabilities = {"new_hook": 0.1, "keep_hook": 0.1, "user_wrote_hook": 0.1, choice: 0.8}
    return {"opening": ChoiceAnswer(choice=choice, confidence=0.8, probabilities=probabilities)}


def _hook(hook: str = HOOK, name: str = "my_rule") -> dict:
    return {"hook_name": name, "hook": hook}


def _system(prompt: str) -> dict:
    block = {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    return {"role": "system", "content": [block]}


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


async def _feedback_version(client, post_id: str, feedback: str = "rewrite it all") -> dict:
    response = await client.post(_versions_url(post_id), json={"feedback": feedback})
    assert response.status_code == 201, response.text
    return response.json()


async def _stored_attempts(db):
    result = await db.execute(select(Post).options(selectinload(Post.attempts)))
    [post] = result.scalars()
    return post.attempts


def _calls(fake_llm) -> list[str]:
    return [call.response_model.__name__ for call in fake_llm.calls]


def _feedback_message(feedback: str) -> dict:
    return _user(
        "Change the post you just wrote according to this feedback, and change "
        "nothing else. Keep every part the feedback does not ask about exactly "
        "as it is, and return the whole post rather than only the part that "
        f"changed.\n\nThe feedback:\n{feedback}"
    )


async def test_the_first_version_never_asks_jev(db, post_id, fake_classifier):
    assert fake_classifier.calls == []
    [attempt] = await _stored_attempts(db)
    assert (attempt.hook_check, attempt.hook_check_probabilities, attempt.hook_check_model) == (
        None,
        None,
        None,
    )


async def test_jev_gets_only_the_conversation_the_user_saw(
    client, post_id, fake_llm, fake_classifier
):
    fake_llm.replies = [{"post": "draft 2"}, {"post": "final 2"}]
    fake_classifier.replies = [_answer("keep_hook")]
    await _feedback_version(client, post_id, feedback="shorter")
    fake_llm.replies = [{"post": "draft 3"}, {"post": "final 3"}]
    fake_classifier.replies = [_answer("keep_hook")]

    await _feedback_version(client, post_id, feedback="warmer")

    assert fake_classifier.calls[-1].state == {
        "conversation": [
            {"from": "user", "text": "ship small things"},
            {"from": "pumpkit", "text": "final 1"},
            {"from": "user", "text": "shorter"},
            {"from": "pumpkit", "text": "final 2"},
            {"from": "user", "text": "warmer"},
        ]
    }


async def test_jev_is_asked_one_choice_question_on_the_pinned_model(
    client, post_id, fake_llm, fake_classifier, monkeypatch
):
    monkeypatch.setattr(settings, "TYPESAFE_MODEL", "jev-9.9.9")
    fake_llm.replies = [{"post": "draft 2"}, {"post": "final 2"}]
    fake_classifier.replies = [_answer("keep_hook")]

    await _feedback_version(client, post_id)

    [call] = fake_classifier.calls
    assert call.model == "jev-9.9.9"
    [(name, question)] = call.questions.items()
    assert name == "opening"
    assert question.type == "choice"
    assert set(question.criteria) == {"new_hook", "keep_hook", "user_wrote_hook"}


async def test_new_hook_runs_the_hook_call_on_the_previous_final_and_the_feedback(
    client, db, post_id, fake_llm, fake_classifier
):
    fake_llm.replies = [_hook(), {"post": DRAFT_2}, {"post": "final 2"}]
    fake_classifier.replies = [_answer("new_hook")]

    version = await _feedback_version(client, post_id, feedback="make it about weekly shipping")

    assert _calls(fake_llm) == ["written_hook", "revised_post", "refined_post"]
    assert fake_llm.calls[0].messages == [
        _system(HOOK_PROMPT),
        _user(LEVELSIO_CORPUS),
        _user(
            "This is the brief the post will be written from. Every fact, number and claim "
            "the hook states must be in it.\n\n"
            "<brief>\nship small things\n</brief>"
        ),
        _user(
            "This is the previous version of the post, the one my feedback below is about."
            "\n\n<post>\nfinal 1\n</post>"
        ),
        _user(
            "This is my feedback on the previous version of the post. The post will be rewritten "
            "from it, and its opening needs a new hook. Facts, numbers and claims in my feedback "
            "may go in the hook too.\n\n"
            "<feedback>\nmake it about weekly shipping\n</feedback>"
        ),
    ]
    assert version["draft"] == DRAFT_2
    attempt = (await _stored_attempts(db))[-1]
    assert (
        attempt.hook_name,
        attempt.hook_text,
        attempt.hook_followed,
        attempt.hooking_model,
    ) == ("my_rule", HOOK, True, DEFAULT_MODEL)
    assert attempt.hooking_usage is not None


async def test_the_revision_call_is_told_to_start_with_the_new_hook_after_the_feedback(
    client, post_id, fake_llm, fake_classifier
):
    fake_llm.replies = [_hook(), {"post": DRAFT_2}, {"post": "final 2"}]
    fake_classifier.replies = [_answer("new_hook")]

    await _feedback_version(client, post_id, feedback="make it about weekly shipping")

    assert fake_llm.calls[1].messages == [
        _system(DRAFT_POST_PROMPT),
        _user(LEVELSIO_CORPUS),
        _user("ship small things"),
        {"role": "assistant", "content": "final 1"},
        _feedback_message("make it about weekly shipping"),
        _user(
            "Start the post with this hook, exactly as written, on its own line or lines. "
            "It replaces the post's current opening. "
            "Then write the rest of the post so it pays the hook off.\n\n"
            f"<hook>\n{HOOK}\n</hook>"
        ),
    ]


async def test_earlier_hooks_are_not_replayed_to_the_revision_call(
    client, post_id, fake_llm, fake_classifier
):
    fake_llm.replies = [_hook(), {"post": DRAFT_2}, {"post": "final 2"}]
    fake_classifier.replies = [_answer("new_hook")]
    await _feedback_version(client, post_id, feedback="make it about weekly shipping")
    fake_llm.calls.clear()
    fake_llm.replies = [{"post": "draft 3"}, {"post": "final 3"}]
    fake_classifier.replies = [_answer("keep_hook")]

    await _feedback_version(client, post_id, feedback="warmer")

    assert fake_llm.calls[0].messages[3:] == [
        {"role": "assistant", "content": "final 1"},
        _feedback_message("make it about weekly shipping"),
        {"role": "assistant", "content": "final 2"},
        _feedback_message("warmer"),
    ]


async def test_a_failed_hook_call_after_new_hook_revises_without_a_hook_and_logs_it(
    client, db, post_id, fake_llm, fake_classifier, caplog
):
    fake_llm.replies = [_hook(name="made_up"), {"post": DRAFT_2}, {"post": "final 2"}]
    fake_classifier.replies = [_answer("new_hook")]

    with caplog.at_level(logging.WARNING):
        version = await _feedback_version(client, post_id, feedback="shorter")

    assert version["draft"] == DRAFT_2
    assert fake_llm.calls[1].messages[-1] == _feedback_message("shorter")
    assert "Hook call failed" in caplog.text
    attempt = (await _stored_attempts(db))[-1]
    assert (attempt.hook_text, attempt.hook_check) == (None, "new_hook")


async def test_new_hook_with_no_hook_written_revises_as_without_one(
    client, db, post_id, fake_llm, fake_classifier
):
    fake_llm.replies = [no_hook(), {"post": DRAFT_2}, {"post": "final 2"}]
    fake_classifier.replies = [_answer("new_hook")]

    await _feedback_version(client, post_id, feedback="shorter")

    assert fake_llm.calls[1].messages[-1] == _feedback_message("shorter")
    attempt = (await _stored_attempts(db))[-1]
    assert (attempt.hook_text, attempt.hook_followed, attempt.hooking_model) == (
        None,
        None,
        DEFAULT_MODEL,
    )


@pytest.mark.parametrize("label", ["keep_hook", "user_wrote_hook"])
async def test_any_other_label_skips_the_hook_call_and_the_hook_message(
    client, db, post_id, fake_llm, fake_classifier, label
):
    fake_llm.replies = [{"post": DRAFT_2}, {"post": "final 2"}]
    fake_classifier.replies = [_answer(label)]

    version = await _feedback_version(client, post_id, feedback="shorter")

    assert _calls(fake_llm) == ["revised_post", "refined_post"]
    assert fake_llm.calls[0].messages[-1] == _feedback_message("shorter")
    assert version["draft"] == DRAFT_2
    attempt = (await _stored_attempts(db))[-1]
    assert (attempt.hook_text, attempt.hooking_model, attempt.hooking_usage) == (None, None, None)
    assert attempt.hook_check == label


async def test_the_top_label_decides_however_close_the_call(
    client, post_id, fake_llm, fake_classifier
):
    probabilities = {"new_hook": 0.34, "keep_hook": 0.33, "user_wrote_hook": 0.33}
    fake_classifier.replies = [
        {"opening": ChoiceAnswer(choice="new_hook", confidence=0.34, probabilities=probabilities)}
    ]
    fake_llm.replies = [no_hook(), {"post": DRAFT_2}, {"post": "final 2"}]

    await _feedback_version(client, post_id)

    assert _calls(fake_llm) == ["written_hook", "revised_post", "refined_post"]


async def test_the_version_stores_jevs_label_probabilities_and_model(
    client, db, post_id, fake_llm, fake_classifier
):
    fake_llm.replies = [{"post": DRAFT_2}, {"post": "final 2"}]
    fake_classifier.replies = [_answer("user_wrote_hook")]

    await _feedback_version(client, post_id)

    attempt = (await _stored_attempts(db))[-1]
    assert attempt.hook_check == "user_wrote_hook"
    assert attempt.hook_check_probabilities == {
        "new_hook": 0.1,
        "keep_hook": 0.1,
        "user_wrote_hook": 0.8,
    }
    assert attempt.hook_check_model == "jev-1.13.0"


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(ClassifierError("Jev returned HTTP 500"), id="jev raises"),
        pytest.param(
            ClassifierError("Jev unreachable: ReadTimeout on each of 2 attempts"),
            id="jev times out",
        ),
        pytest.param(RuntimeError("unexpected"), id="something else raises"),
    ],
)
async def test_a_failed_jev_check_skips_the_hook_call_logs_it_and_writes_the_version(
    client, db, post_id, fake_llm, fake_classifier, caplog, failure
):
    fake_llm.replies = [{"post": DRAFT_2}, {"post": "final 2"}]
    fake_classifier.replies = [failure]

    with caplog.at_level(logging.WARNING):
        version = await _feedback_version(client, post_id)

    assert version["draft"] == DRAFT_2
    assert version["final"] == "final 2"
    assert _calls(fake_llm) == ["revised_post", "refined_post"]
    assert "Jev check failed" in caplog.text
    attempt = (await _stored_attempts(db))[-1]
    assert attempt.status == "succeeded"
    assert (attempt.hook_check, attempt.hook_check_probabilities, attempt.hook_check_model) == (
        None,
        None,
        None,
    )


async def test_without_a_typesafe_key_the_hook_call_is_skipped_and_the_version_written(
    client, db, post_id, fake_llm, caplog, monkeypatch
):
    monkeypatch.setattr(settings, "TYPESAFE_API_KEY", None)
    app.dependency_overrides[get_classifier] = JevClassifier
    fake_llm.replies = [{"post": DRAFT_2}, {"post": "final 2"}]

    with caplog.at_level(logging.INFO):
        version = await _feedback_version(client, post_id)

    assert version["draft"] == DRAFT_2
    assert _calls(fake_llm) == ["revised_post", "refined_post"]
    assert "Jev is not configured" in caplog.text
    assert (await _stored_attempts(db))[-1].hook_check is None
