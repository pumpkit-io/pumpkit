"""The writing prompts: what they interpolate, what they hold, and that the corpus stays out."""

from pumpkit.posts.writing.constants import POST_MAX_CHARS
from pumpkit.posts.writing.prompts.draft_post import DRAFT_POST_PROMPT
from pumpkit.posts.writing.prompts.hook import HOOK_NAMES, HOOK_PROMPT
from pumpkit.posts.writing.prompts.hook_check import HOOK_CHECK_QUESTION
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


def test_no_system_prompt_carries_author_posts():
    for prompt in (DRAFT_POST_PROMPT, HUMANIZER_PROMPT, HOOK_PROMPT):
        assert "<creator" not in prompt
        assert "<post>" not in prompt


def test_the_humanizer_prompt_keeps_the_openings_claim_numbers_and_structure():
    assert (
        "keep the opening's claim, its numbers and its structure, and rewrite only its wording"
        in HUMANIZER_PROMPT
    )


def test_the_hook_prompt_states_the_hard_rules():
    assert "Use only facts, numbers and claims that are in the brief" in HOOK_PROMPT
    assert "A hook that needs a fact you don't have is ruled out" in HOOK_PROMPT
    assert "the writers of the real posts would plausibly write" in HOOK_PROMPT
    assert "Name the topic." in HOOK_PROMPT
    assert "The body must pay the hook off." in HOOK_PROMPT


def test_the_hook_prompt_holds_the_single_post_library_and_the_hooks_to_avoid():
    assert {
        "cost_before_after",
        "dear_persona",
        "keep_only_three",
        "show_more_hook",
    } <= HOOK_NAMES
    assert "# Hooks to avoid" in HOOK_PROMPT
    assert "| `ultra_short_declarative` | Last resort: " in HOOK_PROMPT


def test_the_hook_library_leaves_out_hooks_for_threads_articles_quotes_replies_and_images():
    for left_out in ("analyzed_n_patterns", "wish_i_knew", "complete_playbook", "one_page_guide"):
        assert left_out not in HOOK_NAMES
    for term in ("Quote-post", "chart", "Article", "reply hook", "Closing line", "🧵"):
        assert term not in HOOK_PROMPT


def test_the_length_limit_reaches_the_hook_prompt():
    assert f"{POST_MAX_CHARS} characters" in HOOK_PROMPT
    assert "{" not in HOOK_PROMPT


def test_the_hook_prompt_has_no_em_dash_for_a_hook_to_copy():
    assert "—" not in HOOK_PROMPT


def test_the_hook_prompt_knows_it_may_get_my_feedback():
    assert "my latest feedback on its previous version" in HOOK_PROMPT


def test_jev_answers_user_wrote_hook_whenever_the_feedback_dictates_or_edits_the_opening():
    instructions = HOOK_CHECK_QUESTION.instructions
    assert "dictates the opening" in instructions
    assert "asks to change it in any way, answer user_wrote_hook" in instructions
    assert "the user's own opening must never be replaced" in instructions


def test_jev_chooses_between_a_new_hook_keeping_it_and_the_users_own():
    criteria = HOOK_CHECK_QUESTION.criteria
    assert set(criteria) == {"new_hook", "keep_hook", "user_wrote_hook"}
    assert "rewrite the whole post" in criteria["new_hook"]
    assert "only text after the opening" in criteria["keep_hook"]
    assert "dictates the opening" in criteria["user_wrote_hook"]
