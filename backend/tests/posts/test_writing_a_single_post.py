"""
A single post's first Version is written from its Plan and the User's Positioning: five sketches,
the merge, the scrub, the humanizer and the scrub again (ADR 0026). No Inspiration author's posts
reach it.
"""

import re

import pytest
from sqlalchemy import select

from pumpkit.core.config import settings
from pumpkit.core.llm import LLMCall, LLMError
from pumpkit.posts import version_writing
from pumpkit.posts.models import VersionAttempt
from pumpkit.posts.writing import post_writing
from pumpkit.x_connection.x_publisher import XAccount
from tests.positioning.positioning import TEXT, save_positioning
from tests.posts.mcp_writing import single_post_id
from tests.posts.writing_replies import (
    HUMANIZED_POST,
    MERGED_SKETCH,
    POST_IDEAS,
    SKETCHED_POST,
    ideas,
    merged,
    planned_post,
    sketched,
    written_post,
)

POSTS = "/api/v1/posts"
BRIEFS = "/api/v1/briefs"
USAGE = "/api/v1/usage"
BRIEF = "I shipped a pricing page in a weekend and trials went from 12 to 31 a week."
CACHED = {"type": "ephemeral", "ttl": "1h"}
INPUTS = (
    f"<raw_input>\n{BRIEF}\n</raw_input>\n\n"
    f"<positioning>\n{TEXT}\n</positioning>\n\n"
    "<core_idea>\nShipping small things beats planning big ones.\n</core_idea>\n\n"
    "<takeaway>\nShip the smallest thing that works this week.\n</takeaway>\n\n"
    "<choices>\nfunnel: MOF\ndesired_action: bookmark\nformat: short\nstructure: few_lines\n"
    "</choices>"
)


@pytest.fixture
async def ready(client, subscribed):
    """A User with a Positioning and no Inspiration authors."""
    await save_positioning(client)


@pytest.fixture
def premium(fake_x_publisher, connect_x):
    """Connects the User's X account as a Premium one, whose posts hold 25,000 characters."""

    async def _connect() -> None:
        fake_x_publisher.account = XAccount(
            user_id="1001", handle="ada", subscription_type="Premium"
        )
        await connect_x()

    return _connect


def _angle(call: LLMCall) -> str:
    """The hook type a sketch call was asked to try first."""
    match = re.search(r"around the `(\w+)` hook type", call.messages[1]["content"])
    assert match is not None
    return match.group(1)


def _by_angle(call: LLMCall) -> dict:
    return sketched(f"A {_angle(call)} sketch.", hook_types=[_angle(call)])


async def _write(client, fake_llm, final: str = "The final.", **plan):
    if plan:
        fake_llm.standing[POST_IDEAS] = ideas(planned_post(**plan))
    fake_llm.replies = [{"post": final, "first_reply": None}]
    return await client.post(BRIEFS, json={"brief": BRIEF})


def _calls(fake_llm, schema: type) -> list[LLMCall]:
    return [call for call in fake_llm.calls if call.response_model is schema]


def _system_text(call: LLMCall) -> str:
    [block] = call.messages[0]["content"]
    assert block["cache_control"] == CACHED
    return block["text"]


async def _guide(client, fake_llm, **plan) -> str:
    """The sketch prompt written for a Plan with these choices."""
    response = await _write(client, fake_llm, **plan)
    assert response.status_code == 201, response.text
    return _system_text(_calls(fake_llm, SKETCHED_POST)[0])


async def _version(db) -> VersionAttempt:
    [attempt] = (await db.scalars(select(VersionAttempt))).all()
    return attempt


async def _generations_used(client) -> int:
    return (await client.get(USAGE)).json()["allowance"]["generations"]["used"]


async def test_a_user_with_a_positioning_and_no_inspiration_authors_writes_a_single_post(
    client, ready, fake_llm
):
    response = await _write(client, fake_llm, final="Trials went 12 → 31—in a week.")

    [version] = (await written_post(client, response))["versions"]
    assert [part["text"] for part in version["parts"]] == ["Trials went 12 -> 31 - in a week."]
    assert [call.response_model.__name__ for call in fake_llm.calls] == [
        POST_IDEAS,
        *["sketched_post"] * 5,
        "merged_sketch",
        "refined_post",
    ]


async def test_each_sketch_shares_one_system_prompt_and_tries_a_different_hook_type_first(
    client, ready, fake_llm
):
    await _write(client, fake_llm)

    sketches = _calls(fake_llm, SKETCHED_POST)
    assert len({_system_text(call) for call in sketches}) == 1
    assert _system_text(sketches[0]).startswith(
        "# Role\n\nYou write one post on X on my behalf.\n\n# What you are given\n\n"
    )
    assert [_angle(call) for call in sketches] == [
        "proof",
        "curiosity_gap",
        "contrarian",
        "clear_outcome",
        "story",
    ]
    assert sketches[1].messages[1] == {
        "role": "user",
        "content": INPUTS
        + "\n\n<angle>\nSeveral writers are sketching this same post, each from a different "
        "angle, so I can compare them. Your angle: build the hook around the `curiosity_gap` "
        "hook type (curiosity gap), combined with one or two other types. If the raw input "
        "can't support that type honestly, use the closest type that it can support and say so "
        "in hook_reasoning. Everything else in the guide applies unchanged.\n</angle>",
    }


async def test_the_merge_reads_every_sketch_numbered_with_its_hook_and_the_same_guide(
    client, ready, fake_llm
):
    fake_llm.standing[SKETCHED_POST] = _by_angle

    await _write(client, fake_llm)

    [merge] = _calls(fake_llm, MERGED_SKETCH)
    system = _system_text(merge)
    assert system.startswith(
        "# Role\n\nYou are the editor of one post on X written on my behalf. 5 writers each "
        "sketched the same post"
    )
    assert "- sketches: the 5 sketches, numbered." in system
    guide = _system_text(_calls(fake_llm, SKETCHED_POST)[0])
    assert "# Structure: a few lines" in guide
    assert "# The guide the writers followed\n\nThe final sketch must follow it too." in system
    assert "# Structure: a few lines" in system
    assert merge.messages[1]["content"].startswith(INPUTS + "\n\n<sketches>\n")
    assert (
        '<sketch number="1">\nhook_levers: proof, payoff\nhook_types: proof\n'
        "hook_reasoning: The brief's numbers make the claim believable.\ncta_type: none\n"
        "<post>\nA proof sketch.\n</post>\n</sketch>"
    ) in merge.messages[1]["content"]
    assert '<sketch number="5">' in merge.messages[1]["content"]
    assert "A story sketch." in merge.messages[1]["content"]


async def test_the_humanizer_gets_its_prompt_the_brief_and_plan_then_the_scrubbed_merged_sketch(
    client, ready, fake_llm
):
    fake_llm.standing[MERGED_SKETCH] = merged("Ship it—then fix it…")

    await _write(client, fake_llm)

    [humanizer] = _calls(fake_llm, HUMANIZED_POST)
    system, brief, sketch = humanizer.messages
    text = _system_text(humanizer)
    assert text.startswith(
        "# Role\n\nYou rewrite one post on X on my behalf to make it sound human, removing any "
        "AI-tellers.\n\nFollow the guidelines below to refine the post you are given, removing "
        "AI-tellers while preserving the post's core intent and the explicit asks in the brief."
        "\n\n# Humanization guidelines"
    )
    assert "- The structure (few_lines): keep the order of the parts" in text
    assert "- The length: at most 280 characters as X counts them" in text
    assert "real X posts" not in text
    assert brief == {
        "role": "user",
        "content": (
            "This is the brief the post below was written from. Use it only to keep the rewrite "
            "true to what it asks for - its position and any explicit asks. Do not add anything "
            f"from it that the post does not already say.\n\n<brief>\n{BRIEF}\n</brief>\n\n"
            "<plan>\ncore_idea: Shipping small things beats planning big ones.\n"
            "takeaway: Ship the smallest thing that works this week.\nfunnel: MOF\n"
            "desired_action: bookmark (cta: none)\nformat: short\nstructure: few_lines\n"
            "</plan>"
        ),
    }
    assert sketch == {"role": "user", "content": "Ship it - then fix it..."}


async def test_sketching_merging_and_humanizing_each_use_their_own_model_setting(
    client, ready, fake_llm, monkeypatch
):
    monkeypatch.setattr(settings, "LLM_SKETCHING_MODEL", "acme/sketcher")
    monkeypatch.setattr(settings, "LLM_MERGING_MODEL", "acme/merger")
    monkeypatch.setattr(settings, "LLM_HUMANIZING_MODEL", "acme/humanizer")

    await _write(client, fake_llm)

    assert [call.model for call in fake_llm.calls[1:]] == [
        *["acme/sketcher"] * 5,
        "acme/merger",
        "acme/humanizer",
    ]
    assert {call.max_tokens for call in fake_llm.calls[1:]} == {20000}


async def test_the_version_stores_the_hook_the_cta_the_sketches_the_merge_and_each_steps_model(
    client, db, ready, fake_llm
):
    fake_llm.standing[SKETCHED_POST] = _by_angle
    fake_llm.standing[MERGED_SKETCH] = merged("The merged—sketch")

    await _write(client, fake_llm, final="The final.")

    version = await _version(db)
    assert version.sketch_parts == ["The merged - sketch"]
    assert version.parts == ["The final."]
    assert version.hook_levers == ["proof", "curiosity_gap"]
    assert version.hook_types == ["proof", "number_list"]
    assert version.cta_type == "bookmark"
    assert (version.hook_name, version.hook_reasoning) == (None, None)
    usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    assert version.sketches is not None and len(version.sketches) == 5
    assert version.sketches[2] == {
        "number": 3,
        "merge_number": 3,
        "angle": "contrarian",
        "model": "openai/gpt-6.1-terra",
        "usage": usage,
        "hook_levers": ["proof", "payoff"],
        "hook_types": ["contrarian"],
        "hook_reasoning": "The brief's numbers make the claim believable.",
        "cta_type": "none",
        "post": "A contrarian sketch.",
        "first_reply": None,
    }
    assert version.merge == {
        "reviews": [
            {"sketch_number": n, "keep": f"keep {n}", "drop": f"drop {n}"} for n in range(1, 6)
        ],
        "reasoning": "Sketch 1's hook, sketch 2's body.",
        "first_reply": None,
    }
    assert (version.sketch_model, version.sketch_usage) == ("openai/gpt-6.1-terra", usage)
    assert (version.humanizing_model, version.humanizing_usage) == ("openai/gpt-6.1-terra", usage)


async def test_a_failed_sketch_is_skipped_and_the_merge_reads_the_others(
    client, db, ready, fake_llm
):
    def _contrarian_fails(call: LLMCall):
        if _angle(call) == "contrarian":
            return LLMError("acme: APIConnectionError: down")
        return _by_angle(call)

    fake_llm.standing[SKETCHED_POST] = _contrarian_fails
    fake_llm.standing[MERGED_SKETCH] = merged(sketches=4)

    response = await _write(client, fake_llm)

    assert response.status_code == 201, response.text
    [merge] = _calls(fake_llm, MERGED_SKETCH)
    assert "4 writers each sketched the same post" in _system_text(merge)
    sketches = merge.messages[1]["content"]
    assert "contrarian" not in sketches
    assert '<sketch number="3">' in sketches and "A clear_outcome sketch." in sketches
    assert '<sketch number="5">' not in sketches
    stored = (await _version(db)).sketches
    assert stored is not None
    assert stored[2] == {
        "number": 3,
        "angle": "contrarian",
        "model": "openai/gpt-6.1-terra",
        "error": "acme: APIConnectionError: down",
    }
    assert [sketch.get("merge_number") for sketch in stored] == [1, 2, None, 3, 4]


async def test_when_every_sketch_fails_the_attempt_fails_and_uses_no_generation(
    client, db, ready, fake_llm, fake_posthog
):
    fake_llm.standing[SKETCHED_POST] = LLMError("acme: APIConnectionError: down")

    response = await _write(client, fake_llm)

    assert (await written_post(client, response))["writing_state"] == "not_written"
    fake_posthog.capture_exception.assert_called_once()
    assert _calls(fake_llm, MERGED_SKETCH) == []
    attempt = await _version(db)
    assert (attempt.status, attempt.parts) == ("failed", None)
    assert attempt.error is not None and "Every sketch call failed" in attempt.error
    assert await _generations_used(client) == 0


async def test_a_merged_sketch_blank_after_the_scrub_fails_the_attempt_before_the_humanizer(
    client, db, ready, fake_llm, fake_posthog
):
    fake_llm.standing[MERGED_SKETCH] = merged("\u200b \n ")

    response = await _write(client, fake_llm)

    assert (await written_post(client, response))["writing_state"] == "not_written"
    fake_posthog.capture_exception.assert_called_once()
    assert _calls(fake_llm, HUMANIZED_POST) == []
    attempt = await _version(db)
    assert attempt.status == "failed"
    assert attempt.error is not None and "blank" in attempt.error
    assert await _generations_used(client) == 0


async def test_a_failed_humanizer_call_fails_the_attempt_and_uses_no_generation(
    client, db, ready, fake_llm, fake_posthog
):
    fake_llm.replies = [LLMError("acme: APIConnectionError: down")]

    response = await client.post(BRIEFS, json={"brief": BRIEF})

    assert (await written_post(client, response))["writing_state"] == "not_written"
    fake_posthog.capture_exception.assert_called_once()
    assert (await _version(db)).status == "failed"
    assert await _generations_used(client) == 0


async def test_a_call_waiting_for_a_free_model_slot_is_not_timed_out_by_its_wait(
    client, db, ready, fake_llm, monkeypatch
):
    monkeypatch.setattr(settings, "LLM_CALLS_IN_FLIGHT", 1)
    monkeypatch.setattr(post_writing, "WRITING_CALL_SECONDS", 0.1)
    # Five sketches one at a time: the last waits 0.2s for its slot, longer than its own time.
    fake_llm.latency = 0.05

    response = await _write(client, fake_llm)

    assert response.status_code == 201, response.text
    stored = (await _version(db)).sketches
    assert stored is not None
    assert [sketch.get("error") for sketch in stored] == [None] * 5


async def test_a_written_single_post_uses_one_generation(client, ready, fake_llm):
    assert await _generations_used(client) == 0

    assert (await _write(client, fake_llm)).status_code == 201

    assert await _generations_used(client) == 1


async def test_writing_a_single_post_over_mcp_needs_no_inspiration_author(
    client, ready, mcp, fake_llm
):
    fake_llm.replies = [{"post": "The final.", "first_reply": None}]

    post_id = await single_post_id(mcp, BRIEF)

    post = await mcp.call_tool("get_post", post_id=post_id)
    [version] = post["structuredContent"]["versions"]
    assert version["parts"][0]["text"] == "The final."
    assert len(_calls(fake_llm, SKETCHED_POST)) == 5


# The writing guide: one test per section the Plan tailors.


@pytest.mark.parametrize(
    ("funnel", "section", "cta"),
    [
        ("TOF", "# Funnel stage: top of funnel (TOF)\n\nThe goal is reach", "top of funnel"),
        ("MOF", "# Funnel stage: middle of funnel (MOF)\n\nThe goal is trust", "middle of funnel"),
        (
            "BOF",
            "# Funnel stage: bottom of funnel (BOF)\n\nThe goal is conversion",
            "bottom of funnel",
        ),
    ],
)
async def test_the_guide_has_the_section_of_the_plans_funnel_stage_only(
    client, ready, fake_llm, funnel, section, cta
):
    guide = await _guide(client, fake_llm, funnel=funnel, desired_action="click")

    assert section in guide
    assert guide.count("# Funnel stage:") == 1
    assert f"## CTAs that fit {cta}" in guide
    assert guide.count("## CTAs that fit") == 1


async def test_the_guide_has_the_section_of_the_plans_desired_action_with_its_levers(
    client, ready, fake_llm
):
    guide = await _guide(client, fake_llm, funnel="TOF", desired_action="reply")

    assert "# Desired action: reply\n\nI want the reader to reply." in guide
    assert (
        "Levers that drive this action on X: surprise + identity. Start from this combination."
        in guide
    )
    assert guide.count("# Desired action:") == 1
    assert "this action is unusual" not in guide


async def test_the_guide_notes_a_desired_action_unusual_for_the_funnel_stage(
    client, ready, fake_llm
):
    guide = await _guide(client, fake_llm, funnel="TOF", desired_action="buy")

    assert "# Desired action: buy" in guide
    assert (
        "Note: this action is unusual for TOF. Keep the depth and tone of the funnel stage" in guide
    )


async def test_the_guide_has_the_short_post_section_at_the_accounts_limit(client, ready, fake_llm):
    guide = await _guide(client, fake_llm, format="short", structure="few_lines")

    assert "# Format: short post\n\n- At most 280 characters as X counts them" in guide
    assert "# Format: medium post" not in guide
    assert "# Format: long post" not in guide


async def test_the_guide_has_the_medium_post_section_on_a_premium_account(
    client, ready, fake_llm, premium
):
    await premium()

    guide = await _guide(client, fake_llm, format="medium", structure="hook_problem_insight_closer")

    assert "# Format: medium post" in guide
    assert (
        "Aim for 350 to 600 characters as X counts them (a link counts as 23). Hard limit: 700 characters"
        in guide
    )
    assert "# Format: short post" not in guide
    [humanizer] = _calls(fake_llm, HUMANIZED_POST)
    assert "- The length: at most 700 characters as X counts them" in _system_text(humanizer)


async def test_the_guide_has_the_long_post_section_with_its_funnels_target(
    client, ready, fake_llm, premium
):
    await premium()

    guide = await _guide(
        client,
        fake_llm,
        format="long",
        funnel="BOF",
        desired_action="sign-up",
        structure="hook_playbook_closer",
    )

    assert "# Format: long post" in guide
    assert "Aim for 900 to 2,000 characters." in guide
    assert "Hard limit: 25,000 characters." in guide


async def test_each_limit_is_the_accounts_when_it_is_lower_than_the_guides(
    client, ready, fake_llm, monkeypatch
):
    monkeypatch.setattr(version_writing, "x_post_max_chars", lambda _subscription_type: 500)

    medium = await _guide(client, fake_llm, format="medium", structure="hook_list_closer")
    fake_llm.calls.clear()
    long = await _guide(client, fake_llm, format="long", structure="hook_list_closer")

    assert "Hard limit: 500 characters: count before you answer." in medium
    assert "Hard limit: 500 characters." in long
    [humanizer] = _calls(fake_llm, HUMANIZED_POST)
    assert "- The length: at most 500 characters" in _system_text(humanizer)


@pytest.mark.parametrize(
    ("structure", "length", "section"),
    [
        ("one_line", "short", "# Structure: one line\n\n- The post is one line"),
        ("few_lines", "short", "# Structure: a few lines\n\n- 2 to 5 short lines."),
        (
            "hook_list_closer",
            "long",
            "# Structure: hook, list, closer\n\n- Hook: says what the list is",
        ),
        (
            "hook_problem_insight_closer",
            "medium",
            "# Structure: hook, problem, insight, closer\n\n- Hook.\n- Problem:",
        ),
        (
            "hook_story_insight_closer",
            "long",
            "# Structure: hook, story, insight, closer\n\n- Hook: drop the reader into the story",
        ),
        (
            "hook_playbook_closer",
            "long",
            "# Structure: hook, playbook, closer\n\n- Hook: the outcome the playbook gets",
        ),
    ],
)
async def test_the_guide_has_the_section_of_the_plans_structure_only(
    client, ready, fake_llm, premium, structure, length, section
):
    await premium()

    guide = await _guide(client, fake_llm, format=length, structure=structure)

    assert section in guide
    assert guide.count("# Structure:") == 1


@pytest.mark.parametrize(
    ("choices", "sentence"),
    [
        (
            {"structure": "one_line", "desired_action": "reply"},
            'For this post: there is no separate closer or CTA line (one-line structure). `cta_type` is "reply" only if the line itself makes that ask, otherwise "none".',
        ),
        (
            {"desired_action": "trust"},
            'For this post: the desired action is trust, which is earned by the post and never asked for. Close on the takeaway. `cta_type` is "none".',
        ),
        (
            {"desired_action": "follow"},
            'For this post: the desired action is follow, so the CTA is "follow", written the way the desired-action section says.',
        ),
    ],
)
async def test_the_closer_section_says_what_this_post_asks_for(
    client, ready, fake_llm, choices, sentence
):
    guide = await _guide(client, fake_llm, **choices)

    assert "# The closer and the CTA\n\n- Never trail off." in guide
    assert sentence in guide


async def test_never_add_allows_emoji_hashtags_and_bullets_the_raw_input_asks_for(
    client, ready, fake_llm
):
    guide = await _guide(client, fake_llm)

    assert (
        "# Never add\n\n- No hashtags and no emoji, unless the raw input asks for it.\n"
        "- No headings or titles. No bold, italic or markdown.\n"
        "- No bullet characters, unless the raw input asks for it. Otherwise list items are "
        'plain lines, numbered "1." only when the order or the count matters.\n'
    ) in guide


# Asks X labels as spam (ADR 0032)

SPAM_ASKS = """\
## Asks X labels as spam

X's spam classifiers label posts that ask for engagement, and a labeled post is hidden from everyone who doesn't follow me. None of these go in the post, a first reply or any part, whatever the desired action:

- Asking people to share, send or forward the post, or to show it to someone ("Send this to…", "Share this with…").
- Asking people to tag someone ("Tag a founder who…").
- Asking people to copy the post's link or paste it somewhere.
- Asking for likes, reposts or follows outright ("like and repost", "RT if…", "follow for more", "turn on notifications").
- Trading something for engagement: a reply or comment keyword ("Reply 'guide' and I'll send it"), a giveaway, "everyone who replies gets…". A DM keyword is fine: it asks for a message, not a public reply.
- Telling people to reply or comment ("drop it below", "comment your answer"). A specific question is fine; an instruction to answer it is not."""


async def test_every_sketch_and_the_merge_get_the_asks_x_labels_as_spam_in_the_closer_section(
    client, ready, fake_llm
):
    await _write(client, fake_llm)

    prompts = [_system_text(call) for call in _calls(fake_llm, SKETCHED_POST)]
    prompts.append(_system_text(_calls(fake_llm, MERGED_SKETCH)[0]))
    assert len(prompts) == 6
    for prompt in prompts:
        closer = prompt.index("# The closer and the CTA")
        assert closer < prompt.index(SPAM_ASKS) < prompt.index("For this post:")


@pytest.mark.parametrize(
    ("choices", "rule"),
    [
        (
            {"funnel": "TOF", "desired_action": "share"},
            '- Never ask for the share. No "send this to", no "tag someone": X labels those '
            "as spam. The post earns the share. Close on the takeaway.",
        ),
        (
            {"desired_action": "bookmark"},
            "- Don't ask for the save unless the raw input asks for it. Close on the takeaway and "
            "let the usefulness do the work.",
        ),
    ],
)
async def test_a_share_or_bookmark_post_earns_the_action_and_never_asks_for_it(
    client, ready, fake_llm, choices, rule
):
    guide = await _guide(client, fake_llm, **choices)

    action = choices["desired_action"]
    assert rule in guide
    assert (
        f"For this post: the desired action is {action}, which is earned by the post and never "
        'asked for. Close on the takeaway. `cta_type` is "none".'
    ) in guide


async def test_a_share_post_names_who_it_is_for(client, ready, fake_llm):
    guide = await _guide(client, fake_llm, funnel="TOF", desired_action="share")

    assert (
        '- Name who it is for, in the hook or the body ("If you run evals for a team of five…").'
    ) in guide
    assert "Send this to a founder" not in guide


async def test_a_follow_post_gives_what_comes_next_and_never_tells_readers_to_follow(
    client, ready, fake_llm
):
    guide = await _guide(client, fake_llm, desired_action="follow")

    assert (
        "- Never tell them to follow. Say what comes next and when; that is the reason to follow."
    ) in guide
    assert "Follow if you want day 2" not in guide


async def test_top_of_funnel_ctas_list_no_share_and_avoid_share_tag_like_and_repost_asks(
    client, ready, fake_llm
):
    guide = await _guide(client, fake_llm, funnel="TOF", desired_action="reply")

    assert (
        "## CTAs that fit top of funnel\n\n"
        "- Best: no CTA at all (the post is the CTA); a specific question about the post's idea; "
        "a follow only when there is a series to follow for, stated as a reason, not an order.\n"
        "- Avoid: links, DMs, and any ask to share, tag, like or repost."
    ) in guide


async def test_the_cta_examples_drop_the_bookmark_ask_and_give_the_follow_reason_without_follow(
    client, ready, fake_llm
):
    guide = await _guide(client, fake_llm)

    assert (
        "Weak CTA -> strong CTA (shape only, never copy the wording):\n\n"
        '- "Follow for more" -> "I\'m documenting the whole build. Day 2 goes up tomorrow."\n'
        '- "Thoughts?" -> "What\'s the one tool you\'d never drop from your stack?"\n'
        '- "Link below" -> "Repo\'s in the first reply. It\'s free."'
    ) in guide
    assert "Bookmark this" not in guide
    assert "Save this for" not in guide


async def test_the_merge_removes_any_ask_x_labels_as_spam(client, ready, fake_llm):
    await _write(client, fake_llm)

    [merge] = _calls(fake_llm, MERGED_SKETCH)
    assert (
        '- A second CTA. Generic engagement bait. Any ask the "Asks X labels as spam" section '
        "forbids. Pushy self-promotion."
    ) in _system_text(merge)


async def test_the_humanizer_removes_share_tag_copy_link_and_reply_for_reward_asks(
    client, ready, fake_llm
):
    await _write(client, fake_llm)

    [humanizer] = _calls(fake_llm, HUMANIZED_POST)
    text = _system_text(humanizer)
    assert (
        "- The closer and the CTA: keep the one specific ask the post makes, if it makes one. "
        "Remove an ask only if it is generic engagement bait or asks people to share, tag, copy "
        "the link, or reply for a reward, and my feedback didn't ask for it."
    ) in text
    assert (
        "| Spam-labeled ask | Must fix | Asks to share, tag, copy the link, like/repost, or reply "
        'for a reward. X labels these as spam. | "Send this to a founder who needs it" / '
        "\"Reply 'RAG' and I'll DM you the doc\" | Delete the ask, unless my feedback asked for "
        "it. A DM keyword is fine "
        "(\"DM me 'RAG' for the doc\"). |"
    ) in text


@pytest.mark.parametrize("cta_type", ["share", "bookmark"])
async def test_a_version_whose_cta_is_share_or_bookmark_still_validates(
    client, db, ready, fake_llm, cta_type
):
    fake_llm.standing[MERGED_SKETCH] = merged(cta_type=cta_type)

    response = await _write(client, fake_llm)

    assert response.status_code == 201, response.text
    assert (await _version(db)).cta_type == cta_type


# Calm hooks, plain link pointers and no added mentions (ADR 0032)

HOOK_EXAMPLES = (
    '- curiosity_gap: "My RAG evals looked perfect for a month. The test set was in the index."',
    '- contrarian: "Posting every day made my account worse. I post three times a week now."',
)
CURIOSITY_GAP_RULE = (
    "- A curiosity gap names its topic and opens one specific question. A gap with no topic "
    '("this changes everything") is clickbait, and readers mark it "not interested".'
)
MENTIONS_RULE = (
    "- No @mentions, unless the raw input names the account and the post is about it. "
    "Never more than one."
)


async def test_the_hook_examples_name_their_topic_and_stay_calm(client, ready, fake_llm):
    guide = await _guide(client, fake_llm)

    for example in HOOK_EXAMPLES:
        assert example in guide
    assert "99% of founders" not in guide
    assert "F*ck" not in guide
    craft = guide[guide.index("## How to craft it") : guide.index("## The hook must be honest")]
    assert CURIOSITY_GAP_RULE in craft


@pytest.mark.parametrize(
    ("desired_action", "funnel"), [("click", "MOF"), ("sign-up", "BOF"), ("buy", "BOF")]
)
async def test_the_pointer_to_the_first_reply_link_is_one_plain_line(
    client, ready, fake_llm, desired_action, funnel
):
    guide = await _guide(client, fake_llm, desired_action=desired_action, funnel=funnel)

    assert (
        "- The pointer to the link, in the post and in `first_reply`, is one plain line "
        '("Repo\'s in the first reply"). No urgency or hype to click ("you NEED to see this", '
        '"before it\'s gone").'
    ) in guide


async def test_never_add_forbids_mentions_the_raw_input_does_not_name(client, ready, fake_llm):
    guide = await _guide(client, fake_llm)

    never_add = guide[guide.index("# Never add") :]
    assert MENTIONS_RULE in never_add
