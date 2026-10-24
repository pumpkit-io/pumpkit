"""The writing prompts: what they interpolate, what they hold, and that the corpus stays out."""

from pumpkit.posts.writing.constants import POST_MAX_CHARS
from pumpkit.posts.writing.prompts.draft_post import DRAFT_POST_PROMPT
from pumpkit.posts.writing.prompts.hook import HOOK_LIBRARY, HOOK_NAMES
from pumpkit.posts.writing.prompts.humanizer import HUMANIZER_PROMPT


def test_the_length_limit_reaches_the_draft_prompt():
    assert f"Under {POST_MAX_CHARS} characters." in DRAFT_POST_PROMPT
    assert POST_MAX_CHARS == 3000


def test_nothing_is_left_uninterpolated_in_the_draft_prompt():
    assert "{" not in DRAFT_POST_PROMPT


def test_the_draft_prompt_asks_for_one_post():
    prompt = DRAFT_POST_PROMPT.lower()

    assert "one post" in prompt
    assert "thread" in prompt


def test_the_draft_prompt_starts_as_v6s_does_and_ends_on_the_post_field():
    assert DRAFT_POST_PROMPT.startswith("# Role\n\nYou write one post on X on my behalf.\n")
    assert DRAFT_POST_PROMPT.endswith(
        "The post field holds the post text and nothing else - no preamble, no quotes around it, "
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


def test_no_system_prompt_carries_author_posts():
    for prompt in (DRAFT_POST_PROMPT, HUMANIZER_PROMPT):
        assert "<creator" not in prompt
        assert "<post>" not in prompt


def test_the_humanizer_prompt_keeps_the_openings_claim_numbers_and_structure():
    assert (
        "keep the opening's claim, its numbers and its structure, and rewrite only its wording"
        in HUMANIZER_PROMPT
    )


def test_the_draft_prompt_holds_the_hook_library_after_its_instructions():
    assert HOOK_LIBRARY in DRAFT_POST_PROMPT
    positions = [
        DRAFT_POST_PROMPT.index(marker)
        for marker in ("# The posts are the writing style", "## Hook library", HOOK_LIBRARY)
    ]
    assert positions == sorted(positions)


def test_the_hook_names_are_the_library_ids():
    assert {"cost_before_after", "dear_persona", "show_more_hook"} <= HOOK_NAMES


def test_the_hook_library_has_no_em_dash_for_a_post_to_copy():
    assert "—" not in HOOK_LIBRARY


def test_the_draft_prompt_asks_for_the_hook_reasoning_first_then_the_hook_name_then_the_post():
    output = DRAFT_POST_PROMPT.split("# Output", 1)[1]
    positions = [output.index(f"- {field}:") for field in ("hook_reasoning", "hook_name", "post")]
    assert positions == sorted(positions)
    assert "one to three sentences" in output
    assert "more natural, casual opening" in output
    assert "null when it opens with none" in output
