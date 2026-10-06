"""The prompts ported from pumpkit-v6: what they interpolate, and that the corpus stays out."""

from app.writing.constants import POST_MAX_CHARS
from app.writing.prompts.draft_post import DRAFT_POST_PROMPT
from app.writing.prompts.humanizer import HUMANIZER_PROMPT


def test_the_length_limit_reaches_the_draft_prompt():
    assert f"Under {POST_MAX_CHARS} characters." in DRAFT_POST_PROMPT
    assert POST_MAX_CHARS == 3000


def test_nothing_is_left_uninterpolated_in_the_draft_prompt():
    assert "{" not in DRAFT_POST_PROMPT


def test_the_draft_prompt_asks_for_one_post():
    prompt = DRAFT_POST_PROMPT.lower()

    assert "one post" in prompt
    assert "thread" in prompt


def test_the_draft_prompt_starts_and_ends_as_v6s_does():
    assert DRAFT_POST_PROMPT.startswith("# Role\n\nYou write one post on X on my behalf.\n")
    assert DRAFT_POST_PROMPT.endswith(
        "Return the post text and nothing else - no preamble, no quotes around it, "
        "no notes about what you did.\n"
    )


def test_nothing_is_left_uninterpolated_in_the_humanizer_prompt():
    # "{name}" is the guidelines' own example of a leftover placeholder.
    assert "{" not in HUMANIZER_PROMPT.replace('"{name}"', "")


def test_the_humanizer_prompt_starts_and_ends_as_v6s_does():
    assert HUMANIZER_PROMPT.startswith(
        "# Role\n\nYou rewrite one post on X on my behalf to make it sound human, "
        "removing any AI-tellers.\n"
    )
    assert HUMANIZER_PROMPT.endswith(
        "Return the rewritten post text and nothing else - no preamble, no quotes around it, "
        "no notes about what you changed.\n"
    )


def test_the_humanizer_prompt_keeps_its_guidelines():
    assert "# Humanization guidelines" in HUMANIZER_PROMPT
    assert "core intent" in HUMANIZER_PROMPT
    assert "explicit asks in the brief" in HUMANIZER_PROMPT
    assert "user turn" in HUMANIZER_PROMPT.lower()


def test_neither_prompt_carries_author_posts():
    for prompt in (DRAFT_POST_PROMPT, HUMANIZER_PROMPT):
        assert "<creator" not in prompt
        assert "<post>" not in prompt
