"""
A single post's first reply (ADR 0027): the last Part of the Text, which the writing puts an
external link in. The Text and each Version record it, and the Post's Format stays post.
"""

from datetime import datetime, timezone

import pytest

from pumpkit.authors.x_reader import FetchedPost
from pumpkit.posts.writing.versions import RevisedPost as RevisedFromCorpus
from tests.media_files import png
from tests.positioning.positioning import save_positioning
from tests.posts.writing_replies import (
    HUMANIZED_POST,
    MERGED_SKETCH,
    REVISED_POST,
    merged,
    revised,
    start_thread,
    written,
    written_thread,
)

POSTS = "/api/v1/posts"
BRIEF = "I built a pricing calculator. Sign up at pumpkit.io/calc to try it."


@pytest.fixture
async def ready(client, subscribed):
    await save_positioning(client)


def _texts(parts: list[dict]) -> list[str]:
    return [part["text"] for part in parts]


async def _written(client, fake_llm, merged_reply, humanized_reply) -> dict:
    fake_llm.standing[MERGED_SKETCH] = merged("The post.", first_reply=merged_reply)
    fake_llm.replies = [{"post": "The post.", "first_reply": humanized_reply}]
    response = await client.post(POSTS, json={"brief": BRIEF})
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_written_first_reply_is_the_last_part_of_a_single_post(client, ready, fake_llm):
    post = await _written(client, fake_llm, "Try it: [link]", "Try it here: [link]")

    [version] = post["versions"]
    assert version["format"] == "post"
    assert version["first_reply"] is True
    assert _texts(version["parts"]) == ["The post.", "Try it here: [link]"]
    detail = (await client.get(f"{POSTS}/{post['id']}")).json()
    assert detail["text"]["format"] == "post"
    assert detail["text"]["first_reply"] is True
    assert _texts(detail["text"]["parts"]) == ["The post.", "Try it here: [link]"]
    [humanizer] = [c for c in fake_llm.calls if c.response_model is HUMANIZED_POST]
    assert humanizer.messages[2]["content"] == (
        "<post>\nThe post.\n</post>\n\n<first_reply>\nTry it: [link]\n</first_reply>"
    )


async def test_a_first_reply_the_humanizer_adds_to_a_post_that_had_none_is_dropped(
    client, ready, fake_llm
):
    post = await _written(client, fake_llm, None, "Follow me for more.")

    [version] = post["versions"]
    assert version["first_reply"] is False
    assert _texts(version["parts"]) == ["The post."]
    [humanizer] = [c for c in fake_llm.calls if c.response_model is HUMANIZED_POST]
    assert humanizer.messages[2]["content"] == "The post."


async def _feedback(client, post_id: str, feedback: str, **body) -> dict:
    response = await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": feedback, **body})
    assert response.status_code == 201, response.text
    return response.json()


async def _text(client, post_id: str) -> dict:
    return (await client.get(f"{POSTS}/{post_id}")).json()["text"]


@pytest.fixture
async def with_reply(client, ready, fake_llm) -> str:
    """A single post "The post." written with the first reply "Try it: [link]"."""
    post = await _written(client, fake_llm, "Try it: [link]", "Try it: [link]")
    fake_llm.calls.clear()
    return post["id"]


@pytest.fixture
async def without_reply(client, ready, fake_llm) -> str:
    """A single post "The post." written with no first reply."""
    post = await _written(client, fake_llm, None, None)
    fake_llm.calls.clear()
    return post["id"]


async def test_feedback_can_add_a_first_reply(client, without_reply, fake_llm):
    fake_llm.standing[REVISED_POST] = revised("The post.", first_reply="Sign up: [link]")
    fake_llm.replies = [{"post": "The post.", "first_reply": "Sign up here: [link]"}]

    version = await _feedback(client, without_reply, "Ask them to sign up, link in a reply")

    assert version["format"] == "post"
    assert version["first_reply"] is True
    assert _texts(version["parts"]) == ["The post.", "Sign up here: [link]"]
    text = await _text(client, without_reply)
    assert text["first_reply"] is True
    assert _texts(text["parts"]) == ["The post.", "Sign up here: [link]"]


async def test_feedback_reads_the_first_reply_and_can_change_it(client, with_reply, fake_llm):
    fake_llm.standing[REVISED_POST] = revised("The post.", first_reply="Get it: pumpkit.io/calc")
    fake_llm.replies = [{"post": "The post.", "first_reply": "Get it: pumpkit.io/calc"}]

    version = await _feedback(client, with_reply, "The link is pumpkit.io/calc")

    assert _texts(version["parts"]) == ["The post.", "Get it: pumpkit.io/calc"]
    [revise] = [c for c in fake_llm.calls if c.response_model is REVISED_POST]
    assert revise.messages[2] == {
        "role": "assistant",
        "content": "<post>\nThe post.\n</post>\n\n<first_reply>\nTry it: [link]\n</first_reply>",
    }
    [humanizer] = [c for c in fake_llm.calls if c.response_model is HUMANIZED_POST]
    assert humanizer.messages[2]["content"] == (
        "This is the post as I last saw it, before my latest feedback.\n\n"
        "<previous_post>\nThe post.\n</previous_post>\n\n"
        "<previous_first_reply>\nTry it: [link]\n</previous_first_reply>"
    )
    assert humanizer.messages[-1]["content"].endswith(
        "<post>\nThe post.\n</post>\n\n<first_reply>\nGet it: pumpkit.io/calc\n</first_reply>"
    )


async def test_feedback_can_remove_the_first_reply(client, with_reply, fake_llm):
    fake_llm.standing[REVISED_POST] = revised("The post.")
    fake_llm.replies = [{"post": "The post.", "first_reply": "Try it: [link]"}]

    version = await _feedback(client, with_reply, "No reply, please")

    assert version["first_reply"] is False
    assert _texts(version["parts"]) == ["The post."]
    text = await _text(client, with_reply)
    assert text["first_reply"] is False
    assert _texts(text["parts"]) == ["The post."]


async def _edit(client, post_id: str, **body):
    return await client.put(f"{POSTS}/{post_id}/text", json=body)


async def test_the_user_edits_the_first_reply_as_any_other_part(client, with_reply):
    edited = await _edit(client, with_reply, parts=["The post.", "Try it: pumpkit.io/calc"])

    assert edited.status_code == 200, edited.text
    assert edited.json()["first_reply"] is True
    assert edited.json()["edited"] is True
    assert _texts(edited.json()["parts"]) == ["The post.", "Try it: pumpkit.io/calc"]


async def test_the_user_removes_the_first_reply_and_can_put_it_back(client, with_reply):
    removed = await _edit(client, with_reply, parts=["The post."], first_reply=False)

    assert removed.status_code == 200, removed.text
    assert removed.json()["format"] == "post"
    assert removed.json()["first_reply"] is False
    assert removed.json()["edited"] is True
    assert _texts(removed.json()["parts"]) == ["The post."]

    back = await _edit(client, with_reply, parts=["The post.", "Try it: [link]"], first_reply=True)

    assert back.status_code == 200, back.text
    assert back.json()["first_reply"] is True
    assert back.json()["edited"] is False


async def test_the_user_adds_a_first_reply_to_a_single_post(client, without_reply):
    added = await _edit(client, without_reply, parts=["The post.", "More here."], first_reply=True)

    assert added.status_code == 200, added.text
    assert added.json()["format"] == "post"
    assert added.json()["first_reply"] is True
    assert _texts(added.json()["parts"]) == ["The post.", "More here."]


async def test_editing_without_saying_keeps_the_first_reply_and_the_part_count(client, with_reply):
    refused = await _edit(client, with_reply, parts=["The post."])

    assert refused.status_code == 409
    assert refused.json()["detail"] == (
        "Editing keeps the post and its first reply. Remove the first reply to save the post alone."
    )
    assert (await _text(client, with_reply))["first_reply"] is True


async def test_a_thread_has_no_first_reply(client, subscribed, post_with):
    post_id = await post_with("One", "Two")

    refused = await _edit(client, post_id, parts=["One", "Two", "Three"], first_reply=True)

    assert refused.status_code == 409
    assert refused.json()["detail"] == "Only a single post has a first reply."


async def test_feedback_on_a_hand_edited_first_reply_shows_the_text_as_changed(
    client, with_reply, fake_llm
):
    await _edit(client, with_reply, parts=["The post.", "Try it: pumpkit.io/calc"])
    fake_llm.standing[REVISED_POST] = revised("The post.", first_reply="Try it: pumpkit.io/calc")
    fake_llm.replies = [{"post": "The post.", "first_reply": "Try it: pumpkit.io/calc"}]

    await _feedback(client, with_reply, "Shorter")

    [revise] = [c for c in fake_llm.calls if c.response_model is REVISED_POST]
    assert revise.messages[-1]["content"].startswith(
        "That was Version 1. I changed the text to:\n\n"
        "<post>\nThe post.\n</post>\n\n<first_reply>\nTry it: pumpkit.io/calc\n</first_reply>"
        "\n\nChange my post above"
    )


async def test_media_in_the_first_replys_place_moves_onto_the_post(
    client, subscribed, post_with, next_version
):
    post_id = await post_with("One.", "Two.")
    await next_version(post_id, "The post.", "Try it: pumpkit.io/calc", first_reply=True)
    await client.post(f"{POSTS}/{post_id}/versions/1/restore")
    attached = await client.post(
        f"{POSTS}/{post_id}/text/parts/2/media", files={"file": ("p.png", png(), "image/png")}
    )
    assert attached.status_code == 201, attached.text

    restored = await client.post(f"{POSTS}/{post_id}/versions/2/restore")

    assert restored.status_code == 200, restored.text
    assert restored.json()["first_reply"] is True
    assert [[m["id"] for m in part["media"]] for part in restored.json()["parts"]] == [
        [attached.json()["id"]],
        [],
    ]


@pytest.fixture
async def with_author(client, ready, fake_x_reader):
    fake_x_reader.posts["levelsio"] = [
        FetchedPost(
            post_id="levelsio-0",
            text="levelsio post",
            posted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
    ]
    added = await client.post("/api/v1/inspiration-authors", json={"handle": "levelsio"})
    assert added.status_code == 201, added.text


def _prompts(fake_llm) -> str:
    return "\n".join(
        str(message["content"]) for call in fake_llm.calls for message in call.messages
    )


async def test_feedback_written_from_the_corpus_keeps_the_first_reply_as_it_is(
    client, with_author, fake_llm
):
    started = await start_thread(client, fake_llm, ["a", "b"], brief=BRIEF)
    post_id = started.json()["id"]
    fake_llm.replies = [written("one post"), {"post": "One post."}]
    await _feedback(client, post_id, "condense it", format="post")
    added = await _edit(client, post_id, parts=["One post.", "Try it: x.co/c"], first_reply=True)
    assert added.status_code == 200, added.text
    fake_llm.calls.clear()
    fake_llm.replies = [written("one shorter post"), {"post": "One shorter post."}]

    version = await _feedback(client, post_id, "shorter")

    assert version["format"] == "post"
    assert version["first_reply"] is True
    assert _texts(version["parts"]) == ["One shorter post.", "Try it: x.co/c"]
    assert "x.co/c" not in _prompts(fake_llm)
    assert "<first_reply>" not in _prompts(fake_llm)


async def test_a_switch_to_a_thread_and_back_never_shows_the_model_a_tagged_post(
    client, with_author, fake_llm
):
    post = await _written(client, fake_llm, "Try it: [link]", "Try it: [link]")
    fake_llm.calls.clear()
    fake_llm.replies = [written_thread(["a", "b"]), {"parts": ["a", "b"]}]
    await _feedback(client, post["id"], "expand it", format="thread")
    fake_llm.replies = [written("back"), {"post": "Back to one."}]

    version = await _feedback(client, post["id"], "condense it", format="post")

    assert _texts(version["parts"]) == ["Back to one."]
    assert "<first_reply>" not in _prompts(fake_llm)


async def _switched_to_a_thread(client, fake_llm, reply: str, parts: list[str]) -> dict:
    post = await _written(client, fake_llm, "Try it: [link]", reply)
    fake_llm.replies = [written_thread(["a", "b"]), {"parts": parts}]
    return await _feedback(client, post["id"], "expand it", format="thread")


async def test_a_switch_to_a_thread_ends_its_last_part_with_the_first_reply(
    client, with_author, fake_llm
):
    version = await _switched_to_a_thread(client, fake_llm, "Try it → [link]", ["One.", "Two."])

    assert version["format"] == "thread"
    assert version["first_reply"] is False
    assert _texts(version["parts"]) == ["One.", "Two.\n\nTry it -> [link]"]


async def test_a_first_reply_that_would_overfill_the_last_part_becomes_a_part_of_its_own(
    client, with_author, fake_llm
):
    full = "x" * 270

    version = await _switched_to_a_thread(client, fake_llm, "Try it: [link]", ["One.", full])

    assert _texts(version["parts"]) == ["One.", full, "Try it: [link]"]


async def test_a_thread_of_ten_parts_takes_the_first_reply_into_its_last_part_anyway(
    client, with_author, fake_llm
):
    parts = [f"Part {n}." for n in range(1, 10)] + ["x" * 270]

    version = await _switched_to_a_thread(client, fake_llm, "Try it: [link]", parts)

    assert len(version["parts"]) == 10
    assert version["parts"][-1]["text"] == "x" * 270 + "\n\nTry it: [link]"


async def _corpus_post(client, fake_llm) -> str:
    """A single post "One post." written from the corpus, as Version 2 after a Thread."""
    started = await start_thread(client, fake_llm, ["a", "b"], brief=BRIEF)
    post_id = started.json()["id"]
    fake_llm.replies = [written("one post"), {"post": "One post."}]
    await _feedback(client, post_id, "condense it", format="post")
    return post_id


def _feedback_framings(fake_llm) -> list[str]:
    [revise] = [c for c in fake_llm.calls if c.response_model is RevisedFromCorpus]
    return [
        m["content"]
        for m in revise.messages
        if m["role"] == "user" and m["content"].startswith("That was Version")
    ]


async def test_adding_a_first_reply_to_a_post_written_from_the_corpus_is_no_going_back(
    client, with_author, fake_llm
):
    post_id = await _corpus_post(client, fake_llm)
    added = await _edit(client, post_id, parts=["One post.", "Try it: x.co/c"], first_reply=True)
    assert added.status_code == 200, added.text
    fake_llm.replies = [written("one shorter post"), {"post": "One shorter post."}]
    await _feedback(client, post_id, "shorter")
    fake_llm.calls.clear()
    fake_llm.replies = [written("shortest"), {"post": "Shortest."}]

    await _feedback(client, post_id, "shorter still")

    framings = _feedback_framings(fake_llm)
    assert framings[-2].startswith("That was Version 2.\n\nChange the post you just wrote")
    assert framings[-1].startswith("That was Version 3.\n\nChange the post you just wrote")
    assert not any("went back" in framing for framing in framings)


async def _with_a_blank_first_reply(client, fake_llm) -> str:
    """A post written from the corpus whose User added a first reply and left it blank."""
    post_id = await _corpus_post(client, fake_llm)
    added = await _edit(client, post_id, parts=["One post.", ""], first_reply=True)
    assert added.status_code == 200, added.text
    return post_id


async def test_a_switch_to_a_thread_appends_no_blank_first_reply(client, with_author, fake_llm):
    post_id = await _with_a_blank_first_reply(client, fake_llm)
    fake_llm.replies = [written_thread(["a", "b"]), {"parts": ["One.", "x" * 279]}]

    version = await _feedback(client, post_id, "expand it", format="thread")

    assert _texts(version["parts"]) == ["One.", "x" * 279]


async def test_feedback_on_a_post_with_a_blank_first_reply_drops_it(client, with_author, fake_llm):
    post_id = await _with_a_blank_first_reply(client, fake_llm)
    fake_llm.replies = [written("one shorter post"), {"post": "One shorter post."}]

    version = await _feedback(client, post_id, "shorter")

    assert version["first_reply"] is False
    assert _texts(version["parts"]) == ["One shorter post."]
