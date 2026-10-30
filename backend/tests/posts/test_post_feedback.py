from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pumpkit.auth.models import User
from pumpkit.authors.x_reader import FetchedPost
from pumpkit.core.config import settings
from pumpkit.core.time import as_utc
from pumpkit.posts.llm import LLMError
from pumpkit.posts.models import Post
from pumpkit.posts.writing.prompts.humanizer import HUMANIZER_PROMPT
from pumpkit.posts.writing.prompts.sketch_post import sketch_post_prompt
from pumpkit.x_connection.x_length import X_POST_MAX_CHARS
from tests.posts.writing_replies import written

AUTHORS = "/api/v1/inspiration-authors"
POSTS = "/api/v1/posts"
# The model the prompts were tuned against, used for every call unless a setting says otherwise.
DEFAULT_MODEL = "openai/gpt-5.6-luna"


def _versions_url(post_id: str) -> str:
    return f"{POSTS}/{post_id}/versions"


def _posts(handle: str, count: int) -> list[FetchedPost]:
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    return [
        FetchedPost(
            post_id=f"{handle}-{n}", text=f"{handle} post {n}", posted_at=start - timedelta(hours=n)
        )
        for n in range(count)
    ]


@pytest.fixture
async def post_id(client, subscribed, fake_x_reader, fake_llm) -> str:
    """A Post from the Brief "ship small things" whose first version's text is "final 1"."""
    fake_x_reader.posts["levelsio"] = _posts("levelsio", 2)
    assert (await client.post(AUTHORS, json={"handle": "levelsio"})).status_code == 201
    fake_llm.replies = [written("sketch 1"), {"post": "final 1"}]
    response = await client.post(POSTS, json={"brief": "ship small things"})
    assert response.status_code == 201
    fake_llm.calls.clear()
    return response.json()["id"]


async def test_feedback_returns_a_new_version_with_the_next_number(client, post_id, fake_llm):
    fake_llm.replies = [written("sketch 2—shorter"), {"post": "final 2"}]

    response = await client.post(_versions_url(post_id), json={"feedback": "make it shorter"})

    assert response.status_code == 201
    version = response.json()
    assert version["number"] == 2
    assert version["feedback"] == "make it shorter"
    assert version["format"] == "post"
    assert version["parts"] == [
        {"text": "final 2", "char_count": 7, "char_limit": X_POST_MAX_CHARS}
    ]
    assert version["starting_text"] is None


def _system(prompt: str) -> dict:
    block = {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral", "ttl": "1h"}}
    return {"role": "system", "content": [block]}


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


def _assistant(content: str) -> dict:
    return {"role": "assistant", "content": content}


def _framed(feedback: str, version: int) -> str:
    """
    pumpkit-v6's feedback message after the number of the Version it was given on, typed out here
    so a drift in the port fails the test.
    """
    return (
        f"That was Version {version}.\n\n"
        "Change the post you just wrote according to this feedback, and change nothing else. "
        "Keep every part the feedback does not ask about exactly as it is, and return the whole "
        "post rather than only the part that changed.\n\n"
        f"The feedback:\n{feedback}"
    )


LEVELSIO_CORPUS = (
    "Below are real posts by the writers whose voice you are reproducing, grouped by author. "
    "They are examples of HOW to write, never of what to write about.\n\n"
    '<creator handle="levelsio">\n'
    "<post>levelsio post 0</post>\n"
    "<post>levelsio post 1</post>\n"
    "</creator>"
)


async def test_the_revision_call_continues_the_conversation_with_finals_and_feedback(
    client, post_id, fake_llm
):
    fake_llm.replies = [
        written("sketch 2"),
        {"post": "final 2"},
        written("sketch 3"),
        {"post": "final 3"},
    ]

    await client.post(_versions_url(post_id), json={"feedback": "shorter"})
    await client.post(_versions_url(post_id), json={"feedback": "  warmer\n"})

    first_revision, _, second_revision, _ = fake_llm.calls
    assert first_revision.model == DEFAULT_MODEL
    assert first_revision.response_model.__name__ == "revised_post"
    assert first_revision.messages == [
        _system(sketch_post_prompt(X_POST_MAX_CHARS)),
        _user(LEVELSIO_CORPUS),
        _user("ship small things"),
        _assistant("final 1"),
        _user(_framed("shorter", 1)),
    ]
    assert second_revision.messages == [
        _system(sketch_post_prompt(X_POST_MAX_CHARS)),
        _user(LEVELSIO_CORPUS),
        _user("ship small things"),
        _assistant("final 1"),
        _user(_framed("shorter", 1)),
        _assistant("final 2"),
        _user(_framed("warmer", 2)),
    ]


async def test_the_revision_call_uses_the_configured_model(client, post_id, fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "LLM_REVISING_MODEL", "llama3.3")
    fake_llm.replies = [written("sketch 2"), {"post": "final 2"}]

    await client.post(_versions_url(post_id), json={"feedback": "shorter"})

    assert fake_llm.calls[0].model == "llama3.3"


def _brief(brief: str) -> str:
    return (
        "This is the brief the post below was written from. Use it only to keep the rewrite "
        "true to what it asks for - its position and any explicit asks. Do not add anything "
        f"from it that the post does not already say.\n\n<brief>\n{brief}\n</brief>"
    )


def _previous(final: str) -> str:
    return (
        "This is the post as I last saw it, before my latest feedback.\n\n"
        f"<previous_post>\n{final}\n</previous_post>"
    )


def _latest_feedback(feedback: str) -> str:
    return (
        "This is my latest feedback on that post. The post below already applies it, so "
        "don't apply it again, and don't add, remove or reorder anything to serve it. If it "
        "asks for something your guidelines would undo, keep what it asks for.\n\n"
        f"<feedback>\n{feedback}\n</feedback>"
    )


def _to_rewrite(sketch: str) -> str:
    return (
        "This is the post to rewrite. Return every sentence that is also in the previous "
        "post exactly as it is in <post> below, even if it moved. A sentence that differs "
        "only in punctuation counts as unchanged. Apply your guidelines only to the "
        "sentences that are new or reworded, and don't add sentences or ideas the post "
        "doesn't have.\n\n"
        f"<post>\n{sketch}\n</post>"
    )


async def test_the_humanizer_gets_the_previous_final_the_feedback_and_the_scrubbed_revision(
    client, post_id, fake_llm
):
    fake_llm.replies = [written("it’s shorter—now"), {"post": "final 2"}]

    await client.post(_versions_url(post_id), json={"feedback": "shorter"})

    humanizer_call = fake_llm.calls[1]
    assert humanizer_call.model == DEFAULT_MODEL
    assert humanizer_call.response_model.__name__ == "refined_post"
    assert humanizer_call.messages == [
        _system(HUMANIZER_PROMPT),
        _user(LEVELSIO_CORPUS),
        _user(_brief("ship small things")),
        _user(_previous("final 1")),
        _user(_latest_feedback("shorter")),
        _user(_to_rewrite("it's shorter - now")),
    ]


def _earlier_feedback(*feedback: str) -> str:
    items = "\n".join(f"<feedback>\n{text}\n</feedback>" for text in feedback)
    return (
        "This is the feedback I gave before my latest, oldest first. Each one was applied when I "
        "gave it, so don't apply any of it again. Read it only so the rewrite doesn't undo "
        "something I asked for that still holds, such as a length or a word I don't want.\n\n"
        f"<earlier_feedback>\n{items}\n</earlier_feedback>"
    )


async def test_the_humanizer_gets_every_earlier_feedback_in_order_framed_as_done(
    client, post_id, fake_llm
):
    fake_llm.replies = [
        written("sketch 2"),
        {"post": "final 2"},
        written("sketch 3"),
        {"post": "final 3"},
        written("sketch 4"),
        {"post": "final 4"},
    ]

    await client.post(_versions_url(post_id), json={"feedback": "keep it under 200 characters"})
    await client.post(_versions_url(post_id), json={"feedback": "write a much longer version"})
    await client.post(_versions_url(post_id), json={"feedback": "shorter"})

    assert fake_llm.calls[5].messages[3:] == [
        _user(_earlier_feedback("keep it under 200 characters", "write a much longer version")),
        _user(_previous("final 3")),
        _user(_latest_feedback("shorter")),
        _user(_to_rewrite("sketch 4")),
    ]


async def test_the_revision_uses_the_posts_corpus_after_the_users_authors_change(
    client, post_id, fake_x_reader, fake_llm
):
    await client.delete(f"{AUTHORS}/levelsio")
    fake_x_reader.posts["paulg"] = _posts("paulg", 1)
    assert (await client.post(AUTHORS, json={"handle": "paulg"})).status_code == 201
    fake_llm.replies = [written("sketch 2"), {"post": "final 2"}]

    response = await client.post(_versions_url(post_id), json={"feedback": "shorter"})

    assert response.status_code == 201
    assert fake_llm.calls[0].messages[1] == _user(LEVELSIO_CORPUS)
    assert fake_llm.calls[1].messages[1] == _user(LEVELSIO_CORPUS)


async def test_feedback_over_100000_characters_returns_422_without_calling_the_model(
    client, post_id, fake_llm
):
    response = await client.post(_versions_url(post_id), json={"feedback": "a" * 100_001})

    assert response.status_code == 422
    assert fake_llm.calls == []


async def test_feedback_of_exactly_100000_characters_is_accepted(client, post_id, fake_llm):
    fake_llm.replies = [written("sketch 2"), {"post": "final 2"}]

    response = await client.post(_versions_url(post_id), json={"feedback": "a" * 100_000})

    assert response.status_code == 201


async def test_blank_feedback_returns_422(client, post_id, fake_llm):
    response = await client.post(_versions_url(post_id), json={"feedback": " \n "})

    assert response.status_code == 422
    assert fake_llm.calls == []


async def test_feedback_on_another_users_post_returns_404(client, db, subscribed, fake_llm, clock):
    bob = User(email="bob@example.com", display_name="Bob")
    db.add(bob)
    await db.flush()
    bobs_post = Post(user_id=bob.id, brief="bob's", corpus_post_ids=[], created_at=clock())
    db.add(bobs_post)
    await db.commit()

    response = await client.post(_versions_url(bobs_post.id), json={"feedback": "shorter"})

    assert response.status_code == 404
    assert fake_llm.calls == []


async def test_feedback_on_a_post_that_does_not_exist_returns_404(client, subscribed, fake_llm):
    response = await client.post(_versions_url("post_missing"), json={"feedback": "shorter"})

    assert response.status_code == 404


async def test_a_user_who_is_not_subscribed_gets_403(client, post_id, db, subscribed, fake_llm):
    await db.delete(subscribed)
    await db.commit()

    response = await client.post(_versions_url(post_id), json={"feedback": "shorter"})

    assert response.status_code == 403
    assert fake_llm.calls == []


async def test_feedback_on_a_post_with_no_version_returns_409(
    client, db, subscribed, fake_x_reader, fake_llm
):
    fake_x_reader.posts["levelsio"] = _posts("levelsio", 1)
    await client.post(AUTHORS, json={"handle": "levelsio"})
    fake_llm.replies = [LLMError("provider down")]
    await client.post(POSTS, json={"brief": "ship"})
    failed_post_id = (await db.execute(select(Post.id))).scalar_one()

    response = await client.post(_versions_url(failed_post_id), json={"feedback": "shorter"})

    assert response.status_code == 409
    assert len(fake_llm.calls) == 1


async def _stored_post(db, post_id: str) -> Post:
    result = await db.execute(
        select(Post).where(Post.id == post_id).options(selectinload(Post.attempts))
    )
    return result.scalar_one()


async def test_a_failed_revision_is_stored_as_a_failed_attempt_and_returns_502(
    client, db, post_id, fake_llm, assert_reported_502, clock
):
    fake_llm.replies = [written("sketch 2"), LLMError("provider timed out")]

    response = await client.post(_versions_url(post_id), json={"feedback": "shorter"})

    assert_reported_502(response)
    post = await _stored_post(db, post_id)
    assert [a.status for a in post.attempts] == ["succeeded", "failed"]
    failed = post.attempts[1]
    assert failed.sequence == 2
    assert failed.feedback == "shorter"
    assert failed.error == "LLMError: provider timed out"
    assert (failed.version_number, failed.parts, failed.format) == (None, None, "post")
    assert as_utc(failed.created_at) == clock()


async def test_a_failed_attempt_stays_out_of_the_conversation_and_the_numbering(
    client, db, post_id, fake_llm
):
    fake_llm.replies = [LLMError("provider down"), written("sketch 2"), {"post": "final 2"}]
    await client.post(_versions_url(post_id), json={"feedback": "shorter"})

    response = await client.post(_versions_url(post_id), json={"feedback": "shorter"})

    assert response.json()["number"] == 2
    assert fake_llm.calls[1].messages[2:] == [
        _user("ship small things"),
        _assistant("final 1"),
        _user(_framed("shorter", 1)),
    ]
    post = await _stored_post(db, post_id)
    assert [(a.sequence, a.version_number) for a in post.attempts] == [(1, 1), (2, None), (3, 2)]


async def test_a_version_stores_its_feedback_models_and_usage(client, db, post_id, fake_llm):
    fake_llm.replies = [written("sketch 2"), {"post": "final 2"}]

    await client.post(_versions_url(post_id), json={"feedback": "shorter"})

    post = await _stored_post(db, post_id)
    version = post.attempts[1]
    assert (version.feedback, version.sketch_parts, version.parts) == (
        "shorter",
        ["sketch 2"],
        ["final 2"],
    )
    assert (version.sketch_model, version.humanizing_model) == (DEFAULT_MODEL, DEFAULT_MODEL)
    assert version.sketch_usage is not None and version.humanizing_usage is not None


def _text_url(post_id: str) -> str:
    return f"{POSTS}/{post_id}/text"


def _restore_url(post_id: str, number: int) -> str:
    return f"{POSTS}/{post_id}/versions/{number}/restore"


def _asked(subject: str, feedback: str) -> str:
    return (
        f"Change {subject} according to this feedback, and change nothing else. Keep every part "
        "the feedback does not ask about exactly as it is, and return the whole post rather than "
        f"only the part that changed.\n\nThe feedback:\n{feedback}"
    )


def _hand_written(*sentences: str) -> str:
    items = "\n".join(f"<sentence>{sentence}</sentence>" for sentence in sentences)
    return (
        "I wrote these sentences myself. Wherever one of them is in the post below, even with "
        "different punctuation, return it exactly as I wrote it here, even if your guidelines "
        "would change it, unless my latest feedback asks to change it.\n\n"
        f"<my_sentences>\n{items}\n</my_sentences>"
    )


def _starting(text: str, version_number: int) -> dict:
    return {
        "format": "post",
        "parts": [{"text": text, "char_count": len(text), "char_limit": X_POST_MAX_CHARS}],
        "version_number": version_number,
    }


@pytest.fixture
async def two_versions(client, post_id, fake_llm) -> str:
    """The Post with Version 2, "final 2", from the Feedback "punchier"."""
    fake_llm.replies = [written("sketch 2"), {"post": "final 2"}]
    assert (await client.post(_versions_url(post_id), json={"feedback": "punchier"})).is_success
    fake_llm.calls.clear()
    return post_id


async def test_feedback_after_restoring_a_version_says_the_user_went_back_to_it(
    client, two_versions, fake_llm
):
    await client.post(_restore_url(two_versions, 1))
    fake_llm.replies = [written("sketch 3"), {"post": "final 3"}]

    response = await client.post(_versions_url(two_versions), json={"feedback": "warmer"})

    assert response.status_code == 201
    assert response.json()["starting_text"] == _starting("final 1", 1)
    revision, humanizer = fake_llm.calls
    assert revision.messages[3:] == [
        _assistant("final 1"),
        _user(_framed("punchier", 1)),
        _assistant("final 2"),
        _user("That was Version 2. I went back to Version 1.\n\n" + _asked("Version 1", "warmer")),
    ]
    assert humanizer.messages[3:] == [
        _user(_earlier_feedback("punchier")),
        _user(_previous("final 1")),
        _user(_latest_feedback("warmer")),
        _user(_to_rewrite("sketch 3")),
    ]


async def test_feedback_after_hand_edits_says_what_the_user_changed_the_text_to(
    client, post_id, fake_llm
):
    edited = "final one. I wrote this bit myself!"
    await client.put(_text_url(post_id), json={"parts": [edited]})
    fake_llm.replies = [written("sketch 2"), {"post": "final 2"}]

    response = await client.post(_versions_url(post_id), json={"feedback": "warmer"})

    assert response.json()["starting_text"] == _starting(edited, 1)
    revision, humanizer = fake_llm.calls
    assert revision.messages[3:] == [
        _assistant("final 1"),
        _user(
            "That was Version 1. I changed the text to:\n\n"
            f"<post>\n{edited}\n</post>\n\n" + _asked("my post above", "warmer")
        ),
    ]
    assert humanizer.messages[3:] == [
        _user(_previous(edited)),
        _user(_latest_feedback("warmer")),
        _user(_hand_written("final one.", "I wrote this bit myself!")),
        _user(_to_rewrite("sketch 2")),
    ]


async def test_only_the_sentences_the_user_typed_or_reworded_count_as_hand_written(
    client, post_id, fake_llm
):
    fake_llm.replies = [
        written("sketch 2"),
        {"post": "Ship small. Ship often!\nThen rest"},
        written("sketch 3"),
        {"post": "final 3"},
    ]
    await client.post(_versions_url(post_id), json={"feedback": "longer"})
    await client.put(
        _text_url(post_id), json={"parts": ["Ship often. Ship small, mostly.\nThen rest."]}
    )

    await client.post(_versions_url(post_id), json={"feedback": "warmer"})

    assert fake_llm.calls[3].messages[6] == _user(_hand_written("Ship small, mostly."))


async def test_feedback_after_restoring_and_editing_says_the_user_went_back_and_changed_it(
    client, two_versions, fake_llm
):
    await client.post(_restore_url(two_versions, 1))
    await client.put(_text_url(two_versions), json={"parts": ["final 1, by hand"]})
    fake_llm.replies = [
        written("sketch 3"),
        {"post": "final 3"},
        written("sketch 4"),
        {"post": "final 4"},
    ]

    await client.post(_versions_url(two_versions), json={"feedback": "warmer"})
    await client.post(_versions_url(two_versions), json={"feedback": "shorter"})

    went_back_and_changed = _user(
        "That was Version 2. I went back to Version 1 and changed it to:\n\n"
        "<post>\nfinal 1, by hand\n</post>\n\n" + _asked("my post above", "warmer")
    )
    assert fake_llm.calls[0].messages[-1] == went_back_and_changed
    assert fake_llm.calls[2].messages[3:] == [
        _assistant("final 1"),
        _user(_framed("punchier", 1)),
        _assistant("final 2"),
        went_back_and_changed,
        _assistant("final 3"),
        _user(_framed("shorter", 3)),
    ]
    assert fake_llm.calls[1].messages[6] == _user(_hand_written("final 1, by hand"))


async def test_a_text_edited_back_to_an_earlier_version_reads_as_going_back_to_it(
    client, two_versions, fake_llm
):
    await client.put(_text_url(two_versions), json={"parts": ["final 1"]})
    fake_llm.replies = [written("sketch 3"), {"post": "final 3"}]

    await client.post(_versions_url(two_versions), json={"feedback": "warmer"})

    assert fake_llm.calls[0].messages[-1] == _user(
        "That was Version 2. I went back to Version 1.\n\n" + _asked("Version 1", "warmer")
    )


async def test_feedback_on_the_latest_version_as_written_stores_no_starting_text(
    client, two_versions, fake_llm
):
    await client.post(_restore_url(two_versions, 1))
    await client.post(_restore_url(two_versions, 2))
    fake_llm.replies = [written("sketch 3"), {"post": "final 3"}]

    response = await client.post(_versions_url(two_versions), json={"feedback": "warmer"})

    assert response.json()["starting_text"] is None
    assert fake_llm.calls[0].messages[-1] == _user(_framed("warmer", 2))


async def test_the_new_version_becomes_the_text_not_edited(client, post_id, fake_llm):
    await client.put(_text_url(post_id), json={"parts": ["by hand"]})
    fake_llm.replies = [written("sketch 2"), {"post": "final 2"}]

    await client.post(_versions_url(post_id), json={"feedback": "warmer"})

    post = (await client.get(f"{POSTS}/{post_id}")).json()
    assert (post["text"]["parts"][0]["text"], post["text"]["version_number"]) == ("final 2", 2)
    assert post["text"]["edited"] is False
    assert [v["starting_text"] for v in post["versions"]] == [None, _starting("by hand", 1)]


async def test_feedback_sent_with_a_text_that_is_not_saved_is_refused(client, post_id, fake_llm):
    await client.put(_text_url(post_id), json={"parts": ["saved by hand"]})

    response = await client.post(
        _versions_url(post_id), json={"feedback": "warmer", "text": ["still typing"]}
    )

    assert response.status_code == 409
    assert "isn't saved" in response.json()["detail"]
    assert fake_llm.calls == []


@pytest.mark.parametrize(
    "text",
    [["x" * 30_001], ["Part."] * 26, []],
    ids=["a part too long", "too many parts", "no parts"],
)
async def test_feedback_sent_with_a_text_out_of_bounds_is_refused(client, post_id, fake_llm, text):
    response = await client.post(_versions_url(post_id), json={"feedback": "warmer", "text": text})

    assert response.status_code == 422
    assert fake_llm.calls == []


async def test_feedback_sent_with_the_saved_text_is_written(client, post_id, fake_llm):
    await client.put(_text_url(post_id), json={"parts": ["saved by hand"]})
    fake_llm.replies = [written("sketch 2"), {"post": "final 2"}]

    response = await client.post(
        _versions_url(post_id), json={"feedback": "warmer", "text": ["saved by hand"]}
    )

    assert response.status_code == 201
