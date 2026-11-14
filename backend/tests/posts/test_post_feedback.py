"""
Feedback on a single post written from its Plan: v5's revise call, the scrub and the revision
humanizer, with Pumpkit's Feedback framings and hand-written sentences message (ADR 0016, 0026).
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pumpkit.auth.models import User
from pumpkit.core.config import settings
from pumpkit.core.llm import LLMCall, LLMError
from pumpkit.core.time import as_utc
from pumpkit.posts.models import Idea, Post
from pumpkit.x_connection.x_length import X_POST_MAX_CHARS
from tests.positioning.positioning import POSITIONING, TEXT, save_positioning
from tests.posts.feedback import latest_version, written_version
from tests.posts.writing_replies import (
    HUMANIZED_POST,
    MERGED_SKETCH,
    POST_IDEAS,
    REVISED_POST,
    SKETCHED_POST,
    humanizer_calls,
    merged,
    revised,
    sketched,
    started_post_id,
)

POSTS = "/api/v1/posts"
BRIEFS = "/api/v1/briefs"
USAGE = "/api/v1/usage"
# The revise call's default, the model v5's revise prompt was tuned against.
REVISING_MODEL = "openai/gpt-6.1-terra"
# The humanizer's default, which Feedback's humanizer call shares with a first Version's.
HUMANIZING_MODEL = "openai/gpt-6.1-terra"
CACHED = {"type": "ephemeral", "ttl": "1h"}
INPUTS = (
    "<raw_input>\nship small things\n</raw_input>\n\n"
    f"<positioning>\n{TEXT}\n</positioning>\n\n"
    "<core_idea>\nShipping small things beats planning big ones.\n</core_idea>\n\n"
    "<takeaway>\nShip the smallest thing that works this week.\n</takeaway>\n\n"
    "<choices>\nfunnel: MOF\ndesired_action: bookmark\nformat: short\nstructure: few_lines\n"
    "</choices>"
)


def _versions_url(post_id: str) -> str:
    return f"{POSTS}/{post_id}/versions"


def _text_url(post_id: str) -> str:
    return f"{POSTS}/{post_id}/text"


def _restore_url(post_id: str, number: int) -> str:
    return f"{POSTS}/{post_id}/versions/{number}/restore"


@pytest.fixture
async def post_id(client, subscribed, fake_llm) -> str:
    """
    A single post written from its Plan for a User with a Positioning and no Inspiration authors:
    the Brief "ship small things", whose first Version's text is "final 1".
    """
    await save_positioning(client)
    fake_llm.standing[SKETCHED_POST] = sketched("A sketch.")
    fake_llm.standing[MERGED_SKETCH] = merged("The merged sketch.")
    fake_llm.replies = [{"post": "final 1"}]
    response = await client.post(BRIEFS, json={"brief": "ship small things"})
    assert response.status_code == 201, response.text
    fake_llm.calls.clear()
    return started_post_id(response)


def _feedback(client, post_id: str, feedback: str, **body):
    return client.post(_versions_url(post_id), json={"feedback": feedback, **body})


def _revise_with(fake_llm, *posts: str) -> None:
    """The revise call answers each of `posts` in turn, one per Feedback."""
    answers = iter(posts)
    fake_llm.standing[REVISED_POST] = lambda _call: revised(next(answers))


def _calls(fake_llm, schema: type) -> list[LLMCall]:
    return [call for call in fake_llm.calls if call.response_model is schema]


def _system_text(call: LLMCall) -> str:
    [block] = call.messages[0]["content"]
    assert block["cache_control"] == CACHED
    return block["text"]


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


def _assistant(content: str) -> dict:
    return {"role": "assistant", "content": content}


def _framed(feedback: str, version: int) -> str:
    """Pumpkit's framing of Feedback on the Version just written, typed out so a drift fails."""
    return (
        f"That was Version {version}.\n\n"
        "Change the post you just wrote according to this feedback, and change nothing else. "
        "Keep every part the feedback does not ask about exactly as it is, and return the whole "
        "post rather than only the part that changed.\n\n"
        f"The feedback:\n{feedback}"
    )


def _asked(subject: str, feedback: str) -> str:
    return (
        f"Change {subject} according to this feedback, and change nothing else. Keep every part "
        "the feedback does not ask about exactly as it is, and return the whole post rather than "
        f"only the part that changed.\n\nThe feedback:\n{feedback}"
    )


# v5's revise system prompt around the writing guide, typed out from pumpkit-new-architecture-v5.
REVISE_PROMPT_HEAD = """\
# Role

You revise one post on X written on my behalf, from my feedback.

# What you are given

- raw_input: my raw idea. It is the only source of facts. It can hold more than this post's idea: when it does, use only what belongs to the core idea below.
- positioning: who I am on X, what I post about and who I write for. The reader of the post is the audience it names.
- core_idea: the one idea the post delivers.
- takeaway: what the reader walks away with.
- funnel, desired_action, format, structure: the kind of post this is, already decided. The guide below is already tailored to them.
- the versions of the post: after these inputs, the conversation holds each version of the post, numbered from Version 1, each followed by my feedback on it. The last message is my latest feedback, on the latest version.

# How to revise

- Do what my latest feedback asks, and only that. Every line it doesn't ask about stays word for word, in its place. Return the whole post, not only the part that changed.
- Keep the hook as it is unless my feedback asks to change it. One exception: when the change leaves the hook promising something the post no longer delivers, fix the hook so it stays honest, and change as little of it as you can.
- The feedback is mine, so it wins. Where it goes against the choices or the guide below (another length, another CTA or none, another structure, a word or a line I want), do what it asks.
- Everything you write new follows the guide. For a new hook, choose the levers, then the hook types, then write it, as the hook section says. A new closer or CTA follows the closer and CTA section. New lines follow "How the lines read" and "Never add".
- A fact, number, name or link I give in the feedback counts as if it were in the raw input. Invent no others.
- My earlier feedback still holds. Don't undo what it asked for unless my latest feedback asks to.
- When the feedback is vague ("make it punchier", "I don't like the ending"), change the smallest part of the post that answers it.
- Stay within the format's length limit unless my feedback asks for another length.
- The revised post still reads as if one person typed it in one go. Where a new line meets an old one, reword the join only as much as it needs.

# The guide the post was written with

What you write new must follow it too.

"""

REVISE_PROMPT_TAIL = """\
# Output

- reasoning: written before the post, in two to five sentences: what my feedback asks for, which lines change and how, and what stays as it is. When you write a new hook, name the levers and hook types you chose and the question the hook raises in the reader's mind.
- cta_type: the CTA the revised post makes, or "none".
- post: the whole revised post and nothing else. No preamble, no quotes around it, no notes about what you changed. Line breaks as they should appear on X.
- first_reply: the text of my first reply under the post, only when the CTA needs an external link or a follow-up there. Keep the one the latest version has unless my feedback changes it. Use a link only if the raw input or my feedback gives one; otherwise write [link] where it goes. null in every other case.
"""

BRIEF_AND_PLAN = (
    "This is the brief the post below was written from. Use it only to keep the rewrite "
    "true to what it asks for - its position and any explicit asks. Do not add anything "
    "from it that the post does not already say.\n\n<brief>\nship small things\n</brief>\n\n"
    "<plan>\ncore_idea: Shipping small things beats planning big ones.\n"
    "takeaway: Ship the smallest thing that works this week.\nfunnel: MOF\n"
    "desired_action: bookmark (cta: bookmark)\nformat: short\nstructure: few_lines\n"
    "</plan>"
)


def _previous(post: str) -> str:
    return (
        "This is the post as I last saw it, before my latest feedback.\n\n"
        f"<previous_post>\n{post}\n</previous_post>"
    )


def _latest_feedback(feedback: str) -> str:
    return (
        "This is my latest feedback on that post. The post below already applies it, so "
        "don't apply it again, and don't add, remove or reorder anything to serve it. If it "
        "asks for something your guidelines would undo, keep what it asks for.\n\n"
        f"<feedback>\n{feedback}\n</feedback>"
    )


def _to_rewrite(post: str) -> str:
    return (
        "This is the post to rewrite. Return every sentence that is also in the previous "
        "post exactly as it is in <post> below, even if it moved. A sentence that differs "
        "only in punctuation counts as unchanged. Apply your guidelines only to the "
        "sentences that are new or reworded, and don't add sentences or ideas the post "
        "doesn't have.\n\n"
        f"<post>\n{post}\n</post>"
    )


def _earlier_feedback(*feedback: str) -> str:
    items = "\n".join(f"<feedback>\n{text}\n</feedback>" for text in feedback)
    return (
        "This is the feedback I gave before my latest, oldest first. Each one was applied when I "
        "gave it, so don't apply any of it again. Read it only so the rewrite doesn't undo "
        "something I asked for that still holds, such as a length or a word I don't want.\n\n"
        f"<earlier_feedback>\n{items}\n</earlier_feedback>"
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
        "first_reply": False,
        "version_number": version_number,
    }


async def _stored_post(db, post_id: str) -> Post:
    result = await db.execute(
        select(Post).where(Post.id == post_id).options(selectinload(Post.attempts))
    )
    return result.scalar_one()


async def _generations_used(client) -> int:
    return (await client.get(USAGE)).json()["allowance"]["generations"]["used"]


async def test_feedback_returns_a_new_version_with_the_next_number(client, post_id, fake_llm):
    fake_llm.replies = [{"post": "final 2"}]

    version = await written_version(client, post_id, "make it shorter")

    assert version["number"] == 2
    assert version["feedback"] == "make it shorter"
    assert version["format"] == "post"
    assert version["parts"] == [
        {"text": "final 2", "char_count": 7, "char_limit": X_POST_MAX_CHARS}
    ]
    assert version["starting_text"] is None


async def test_feedback_on_a_single_post_runs_the_revise_call_then_the_revision_humanizer(
    client, post_id, fake_llm
):
    fake_llm.replies = [{"post": "final 2"}]

    await _feedback(client, post_id, "make it shorter")

    assert [call.response_model for call in fake_llm.calls] == [REVISED_POST, HUMANIZED_POST]
    assert [call.response_model.__name__ for call in fake_llm.calls] == [
        "revised_post",
        "refined_post",
    ]
    assert [call.model for call in fake_llm.calls] == [REVISING_MODEL, HUMANIZING_MODEL]
    assert {call.max_tokens for call in fake_llm.calls} == {20000}


async def test_the_revise_prompt_is_v5s_around_the_guide_of_the_posts_plan(
    client, post_id, fake_llm
):
    fake_llm.replies = [{"post": "final 2"}]

    await _feedback(client, post_id, "make it shorter")

    [revise] = _calls(fake_llm, REVISED_POST)
    system = _system_text(revise)
    assert system.startswith(REVISE_PROMPT_HEAD)
    assert system.endswith(REVISE_PROMPT_TAIL)
    guide = system[len(REVISE_PROMPT_HEAD) : -len(REVISE_PROMPT_TAIL)]
    assert "# Structure: a few lines" in guide
    assert "# Format: short post\n\n- At most 280 characters as X counts them" in guide


async def test_the_revise_conversation_is_the_inputs_then_each_version_after_its_feedback(
    client, post_id, fake_llm
):
    _revise_with(fake_llm, "revised 2", "revised 3")
    fake_llm.replies = [{"post": "final 2"}, {"post": "final 3"}]

    await _feedback(client, post_id, "shorter")
    await _feedback(client, post_id, "  warmer\n")

    first, second = _calls(fake_llm, REVISED_POST)
    assert first.messages[1:] == [
        _user(INPUTS),
        _assistant("final 1"),
        _user(_framed("shorter", 1)),
    ]
    assert second.messages[1:] == [
        _user(INPUTS),
        _assistant("final 1"),
        _user(_framed("shorter", 1)),
        _assistant("final 2"),
        _user(_framed("warmer", 2)),
    ]


async def test_the_revise_conversation_replays_no_sketch_no_merge_and_no_revised_post(
    client, post_id, fake_llm
):
    _revise_with(fake_llm, "revised 2", "revised 3")
    fake_llm.replies = [{"post": "final 2"}, {"post": "final 3"}]

    await _feedback(client, post_id, "shorter")
    await _feedback(client, post_id, "warmer")

    [*_, second] = _calls(fake_llm, REVISED_POST)
    replayed = "\n".join(message["content"] for message in second.messages[1:])
    assert "A sketch." not in replayed
    assert "The merged sketch." not in replayed
    assert "revised 2" not in replayed


async def test_the_revise_call_reads_the_positioning_the_brief_was_planned_with(
    client, post_id, fake_llm
):
    assert (await client.put(POSITIONING, json={"text": "I now post about cooking."})).is_success
    fake_llm.replies = [{"post": "final 2"}]

    await _feedback(client, post_id, "shorter")

    [revise] = _calls(fake_llm, REVISED_POST)
    assert revise.messages[1] == _user(INPUTS)


async def test_the_revise_and_revision_humanizer_calls_use_their_model_settings(
    client, post_id, fake_llm, monkeypatch
):
    monkeypatch.setattr(settings, "LLM_REVISING_MODEL", "acme/reviser")
    monkeypatch.setattr(settings, "LLM_HUMANIZING_MODEL", "acme/humanizer")
    fake_llm.replies = [{"post": "final 2"}]

    await _feedback(client, post_id, "shorter")

    assert [call.model for call in fake_llm.calls] == ["acme/reviser", "acme/humanizer"]


async def test_the_humanizer_gets_the_brief_and_plan_the_previous_post_the_feedback_and_the_scrubbed_revision(
    client, post_id, fake_llm
):
    _revise_with(fake_llm, "it’s shorter—now")
    fake_llm.replies = [{"post": "final 2"}]

    await _feedback(client, post_id, "shorter")

    [humanizer] = _calls(fake_llm, HUMANIZED_POST)
    system = _system_text(humanizer)
    assert system.startswith(
        "# Role\n\nYou rewrite one post on X on my behalf to make it sound human, removing any "
        "AI-tellers."
    )
    assert "- The structure (few_lines): keep the order of the parts" in system
    assert humanizer.messages[1:] == [
        _user(BRIEF_AND_PLAN),
        _user(_previous("final 1")),
        _user(_latest_feedback("shorter")),
        _user(_to_rewrite("it's shorter - now")),
    ]


async def test_the_humanizer_gets_every_earlier_feedback_in_order_framed_as_done(
    client, post_id, fake_llm
):
    _revise_with(fake_llm, "revised 2", "revised 3", "revised 4")
    fake_llm.replies = [{"post": "final 2"}, {"post": "final 3"}, {"post": "final 4"}]

    await _feedback(client, post_id, "keep it under 200 characters")
    await _feedback(client, post_id, "write a much longer version")
    await _feedback(client, post_id, "shorter")

    [*_, humanizer] = _calls(fake_llm, HUMANIZED_POST)
    assert humanizer.messages[2:] == [
        _user(_earlier_feedback("keep it under 200 characters", "write a much longer version")),
        _user(_previous("final 3")),
        _user(_latest_feedback("shorter")),
        _user(_to_rewrite("revised 4")),
    ]


async def test_a_version_stores_its_feedback_the_revised_post_the_reasoning_cta_models_and_usage(
    client, db, post_id, fake_llm
):
    fake_llm.standing[REVISED_POST] = revised(
        "revised—2", reasoning="Cut the middle line.", cta_type="reply"
    )
    fake_llm.replies = [{"post": "final 2"}]

    await _feedback(client, post_id, "shorter")

    post = await _stored_post(db, post_id)
    version = post.attempts[1]
    assert (version.feedback, version.sketch_parts, version.parts) == (
        "shorter",
        ["revised - 2"],
        ["final 2"],
    )
    assert (version.hook_reasoning, version.hook_name, version.cta_type) == (
        "Cut the middle line.",
        None,
        "reply",
    )
    assert (version.sketch_model, version.humanizing_model) == (REVISING_MODEL, HUMANIZING_MODEL)
    assert version.sketch_usage is not None and version.humanizing_usage is not None


async def test_feedback_over_100000_characters_returns_422_without_calling_the_model(
    client, post_id, fake_llm
):
    response = await _feedback(client, post_id, "a" * 100_001)

    assert response.status_code == 422
    assert fake_llm.calls == []


async def test_feedback_of_exactly_100000_characters_is_accepted(client, post_id, fake_llm):
    fake_llm.replies = [{"post": "final 2"}]

    response = await _feedback(client, post_id, "a" * 100_000)

    assert response.status_code == 202


async def test_blank_feedback_returns_422(client, post_id, fake_llm):
    response = await _feedback(client, post_id, " \n ")

    assert response.status_code == 422
    assert fake_llm.calls == []


async def test_feedback_on_another_users_post_returns_404(client, db, subscribed, fake_llm, clock):
    bob = User(email="bob@example.com", display_name="Bob")
    db.add(bob)
    await db.flush()
    bobs_post = Post(user_id=bob.id, brief="bob's", corpus_post_ids=[], created_at=clock())
    db.add(bobs_post)
    await db.commit()

    response = await _feedback(client, bobs_post.id, "shorter")

    assert response.status_code == 404
    assert fake_llm.calls == []


async def test_feedback_on_a_post_that_does_not_exist_returns_404(client, subscribed, fake_llm):
    response = await _feedback(client, "post_missing", "shorter")

    assert response.status_code == 404


async def test_a_user_who_is_not_subscribed_gets_403(client, post_id, db, subscribed, fake_llm):
    await db.delete(subscribed)
    await db.commit()

    response = await _feedback(client, post_id, "shorter")

    assert response.status_code == 403
    assert fake_llm.calls == []


async def test_feedback_on_a_post_with_no_version_returns_409(client, db, subscribed, fake_llm):
    await save_positioning(client)
    fake_llm.replies = [LLMError("provider down")]
    await client.post(BRIEFS, json={"brief": "ship"})
    failed_post_id = (await db.execute(select(Post.id))).scalar_one()

    response = await _feedback(client, failed_post_id, "shorter")

    assert response.status_code == 409
    assert len(humanizer_calls(fake_llm)) == 1


async def test_a_failed_revision_humanizer_is_stored_as_a_failed_attempt_and_reported(
    client, db, post_id, fake_llm, fake_posthog, clock
):
    fake_llm.replies = [LLMError("provider timed out")]

    response = await _feedback(client, post_id, "shorter")

    assert response.status_code == 202, response.text
    fake_posthog.capture_exception.assert_called_once()
    assert (await latest_version(client, post_id))["number"] == 1
    post = await _stored_post(db, post_id)
    assert [a.status for a in post.attempts] == ["succeeded", "failed"]
    failed = post.attempts[1]
    assert failed.sequence == 2
    assert failed.feedback == "shorter"
    assert failed.error == "LLMError: provider timed out"
    assert (failed.version_number, failed.parts, failed.format) == (None, None, "post")
    assert as_utc(failed.created_at) == clock()


@pytest.mark.parametrize(
    ("revised_post", "humanized_post"),
    [(" \n ", "unused"), ("revised 2", "  ")],
    ids=["the revise call", "the revision humanizer"],
)
async def test_a_post_blank_after_the_scrub_fails_the_attempt_and_uses_no_generation(
    client, db, post_id, fake_llm, fake_posthog, revised_post, humanized_post
):
    fake_llm.standing[REVISED_POST] = revised(revised_post)
    fake_llm.replies = [{"post": humanized_post}]
    used = await _generations_used(client)

    response = await _feedback(client, post_id, "shorter")

    assert response.status_code == 202, response.text
    fake_posthog.capture_exception.assert_called_once()
    post = await _stored_post(db, post_id)
    assert [a.status for a in post.attempts] == ["succeeded", "failed"]
    assert await _generations_used(client) == used


async def test_a_failed_attempt_stays_out_of_the_conversation_and_the_numbering(
    client, db, post_id, fake_llm
):
    fake_llm.replies = [LLMError("provider down"), {"post": "final 2"}]
    await _feedback(client, post_id, "shorter")

    version = await written_version(client, post_id, "shorter")

    assert version["number"] == 2
    [_, second] = _calls(fake_llm, REVISED_POST)
    assert second.messages[1:] == [
        _user(INPUTS),
        _assistant("final 1"),
        _user(_framed("shorter", 1)),
    ]
    post = await _stored_post(db, post_id)
    assert [(a.sequence, a.version_number) for a in post.attempts] == [(1, 1), (2, None), (3, 2)]


async def test_a_feedback_version_uses_one_generation(client, post_id, fake_llm):
    fake_llm.replies = [{"post": "final 2"}]
    used = await _generations_used(client)

    await _feedback(client, post_id, "shorter")

    assert await _generations_used(client) == used + 1


@pytest.fixture
async def two_versions(client, post_id, fake_llm) -> str:
    """The Post with Version 2, "final 2", from the Feedback "punchier"."""
    fake_llm.replies = [{"post": "final 2"}]
    assert (await _feedback(client, post_id, "punchier")).is_success
    fake_llm.calls.clear()
    return post_id


async def test_feedback_after_restoring_a_version_says_the_user_went_back_to_it(
    client, two_versions, fake_llm
):
    await client.post(_restore_url(two_versions, 1))
    _revise_with(fake_llm, "revised 3")
    fake_llm.replies = [{"post": "final 3"}]

    version = await written_version(client, two_versions, "warmer")

    assert version["starting_text"] == _starting("final 1", 1)
    revise, humanizer = fake_llm.calls
    assert revise.messages[2:] == [
        _assistant("final 1"),
        _user(_framed("punchier", 1)),
        _assistant("final 2"),
        _user("That was Version 2. I went back to Version 1.\n\n" + _asked("Version 1", "warmer")),
    ]
    assert humanizer.messages[2:] == [
        _user(_earlier_feedback("punchier")),
        _user(_previous("final 1")),
        _user(_latest_feedback("warmer")),
        _user(_to_rewrite("revised 3")),
    ]


async def test_feedback_after_hand_edits_says_what_the_user_changed_the_text_to(
    client, post_id, fake_llm
):
    edited = "final one. I wrote this bit myself!"
    await client.put(_text_url(post_id), json={"parts": [edited]})
    _revise_with(fake_llm, "revised 2")
    fake_llm.replies = [{"post": "final 2"}]

    version = await written_version(client, post_id, "warmer")

    assert version["starting_text"] == _starting(edited, 1)
    revise, humanizer = fake_llm.calls
    assert revise.messages[2:] == [
        _assistant("final 1"),
        _user(
            "That was Version 1. I changed the text to:\n\n"
            f"<post>\n{edited}\n</post>\n\n" + _asked("my post above", "warmer")
        ),
    ]
    assert humanizer.messages[2:] == [
        _user(_previous(edited)),
        _user(_latest_feedback("warmer")),
        _user(_hand_written("final one.", "I wrote this bit myself!")),
        _user(_to_rewrite("revised 2")),
    ]


async def test_only_the_sentences_the_user_typed_or_reworded_count_as_hand_written(
    client, post_id, fake_llm
):
    fake_llm.replies = [{"post": "Ship small. Ship often!\nThen rest"}, {"post": "final 3"}]
    await _feedback(client, post_id, "longer")
    await client.put(
        _text_url(post_id), json={"parts": ["Ship often. Ship small, mostly.\nThen rest."]}
    )

    await _feedback(client, post_id, "warmer")

    [*_, humanizer] = _calls(fake_llm, HUMANIZED_POST)
    assert humanizer.messages[5] == _user(_hand_written("Ship small, mostly."))


async def test_feedback_after_restoring_and_editing_says_the_user_went_back_and_changed_it(
    client, two_versions, fake_llm
):
    await client.post(_restore_url(two_versions, 1))
    await client.put(_text_url(two_versions), json={"parts": ["final 1, by hand"]})
    fake_llm.replies = [{"post": "final 3"}, {"post": "final 4"}]

    await _feedback(client, two_versions, "warmer")
    await _feedback(client, two_versions, "shorter")

    went_back_and_changed = _user(
        "That was Version 2. I went back to Version 1 and changed it to:\n\n"
        "<post>\nfinal 1, by hand\n</post>\n\n" + _asked("my post above", "warmer")
    )
    first_revise, second_revise = _calls(fake_llm, REVISED_POST)
    assert first_revise.messages[-1] == went_back_and_changed
    assert second_revise.messages[2:] == [
        _assistant("final 1"),
        _user(_framed("punchier", 1)),
        _assistant("final 2"),
        went_back_and_changed,
        _assistant("final 3"),
        _user(_framed("shorter", 3)),
    ]
    [first_humanizer, _] = _calls(fake_llm, HUMANIZED_POST)
    assert first_humanizer.messages[5] == _user(_hand_written("final 1, by hand"))


async def test_a_text_edited_back_to_an_earlier_version_reads_as_going_back_to_it(
    client, two_versions, fake_llm
):
    await client.put(_text_url(two_versions), json={"parts": ["final 1"]})
    fake_llm.replies = [{"post": "final 3"}]

    await _feedback(client, two_versions, "warmer")

    [revise] = _calls(fake_llm, REVISED_POST)
    assert revise.messages[-1] == _user(
        "That was Version 2. I went back to Version 1.\n\n" + _asked("Version 1", "warmer")
    )


async def test_feedback_on_the_latest_version_as_written_stores_no_starting_text(
    client, two_versions, fake_llm
):
    await client.post(_restore_url(two_versions, 1))
    await client.post(_restore_url(two_versions, 2))
    fake_llm.replies = [{"post": "final 3"}]

    version = await written_version(client, two_versions, "warmer")

    assert version["starting_text"] is None
    [revise] = _calls(fake_llm, REVISED_POST)
    assert revise.messages[-1] == _user(_framed("warmer", 2))


async def test_the_new_version_becomes_the_text_not_edited(client, post_id, fake_llm):
    await client.put(_text_url(post_id), json={"parts": ["by hand"]})
    fake_llm.replies = [{"post": "final 2"}]

    await _feedback(client, post_id, "warmer")

    post = (await client.get(f"{POSTS}/{post_id}")).json()
    assert (post["text"]["parts"][0]["text"], post["text"]["version_number"]) == ("final 2", 2)
    assert post["text"]["edited"] is False
    assert [v["starting_text"] for v in post["versions"]] == [None, _starting("by hand", 1)]


async def test_feedback_sent_with_a_text_that_is_not_saved_is_refused(client, post_id, fake_llm):
    await client.put(_text_url(post_id), json={"parts": ["saved by hand"]})

    response = await _feedback(client, post_id, "warmer", text=["still typing"])

    assert response.status_code == 409
    assert "isn't saved" in response.json()["detail"]
    assert fake_llm.calls == []


@pytest.mark.parametrize(
    "text",
    [["x" * 30_001], ["Part."] * 26, []],
    ids=["a part too long", "too many parts", "no parts"],
)
async def test_feedback_sent_with_a_text_out_of_bounds_is_refused(client, post_id, fake_llm, text):
    response = await _feedback(client, post_id, "warmer", text=text)

    assert response.status_code == 422
    assert fake_llm.calls == []


async def test_feedback_sent_with_the_saved_text_is_written(client, post_id, fake_llm):
    await client.put(_text_url(post_id), json={"parts": ["saved by hand"]})
    fake_llm.replies = [{"post": "final 2"}]

    version = await written_version(client, post_id, "warmer", text=["saved by hand"])

    assert version["number"] == 2


async def test_feedback_after_switching_to_a_thread_and_back_reads_both_switches(
    client, post_id, fake_llm
):
    fake_llm.replies = [{"parts": ["final a", "final b"]}, {"post": "final 3"}, {"post": "final 4"}]
    assert (await _feedback(client, post_id, "expand it", format="thread")).is_success
    assert (await _feedback(client, post_id, "condense it", format="post")).is_success
    _revise_with(fake_llm, "revised 4")

    await _feedback(client, post_id, "warmer")

    [*_, revise] = _calls(fake_llm, REVISED_POST)
    assert revise.messages[2:] == [
        _assistant("final 1"),
        _user(
            "That was Version 1.\n\n"
            "Rewrite the post you just wrote as a thread, according to this feedback. Keep "
            "what it says and how it says it wherever the feedback does not ask for a change, "
            "spread over the parts the thread needs, and return the whole thread.\n\n"
            "The feedback:\nexpand it"
        ),
        _assistant('<part number="1">\nfinal a\n</part>\n\n<part number="2">\nfinal b\n</part>'),
        _user(
            "That was Version 2.\n\n"
            "Rewrite the thread you just wrote as a single post, according to this feedback. "
            "Keep what it says and how it says it wherever the feedback does not ask for a "
            "change and one post has room for it, and return the whole post. An external "
            "link in the thread, or its [link], goes in the first reply, not in the post.\n\n"
            "The feedback:\ncondense it"
        ),
        _assistant("final 3"),
        _user(_framed("warmer", 3)),
    ]


@pytest.mark.parametrize("format", [None, "post", "thread"])
async def test_feedback_on_a_post_written_before_plans_existed_is_refused(
    client, db, post_id, fake_llm, format
):
    post = await _stored_post(db, post_id)
    idea = await db.get(Idea, post.idea_id)
    assert idea is not None
    idea.core_idea = None
    await db.commit()
    used = await _generations_used(client)

    response = await _feedback(client, post_id, "shorter", **({"format": format} if format else {}))

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "This post was written before plans existed, so it can't take feedback. "
        "Edit the text by hand, or start a new post."
    )
    assert fake_llm.calls == []
    assert await _generations_used(client) == used
    read = (await client.get(f"{POSTS}/{post_id}")).json()
    assert [version["number"] for version in read["versions"]] == [1]


async def test_feedback_makes_no_plan_call(client, post_id, fake_llm):
    fake_llm.replies = [{"post": "final 2"}]

    await _feedback(client, post_id, "make it shorter")

    assert POST_IDEAS not in [call.response_model.__name__ for call in fake_llm.calls]
