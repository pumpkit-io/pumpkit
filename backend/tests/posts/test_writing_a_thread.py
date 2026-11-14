"""
The planner chooses a Thread, and a Thread's first Version is written from its Plan by its own
sketch, merge and humanizer prompts: five sketches, the merge, the scrub, the humanizer and the
scrub again (ADR 0025, ADR 0026). No Inspiration author's posts reach it.
"""

import re

import pytest
from sqlalchemy import select

from pumpkit.core.llm import LLMCall, LLMError
from pumpkit.posts.models import VersionAttempt
from pumpkit.posts.writing.constants import THREAD_MAX_PARTS
from pumpkit.x_connection.x_publisher import XAccount
from tests.positioning.positioning import TEXT, save_positioning
from tests.posts.feedback import written_version
from tests.posts.writing_replies import (
    HUMANIZED_THREAD,
    MERGED_THREAD,
    POST_IDEAS,
    REVISED_THREAD,
    SKETCHED_THREAD,
    ideas,
    merged_thread,
    planned_post,
    planned_thread,
    revised_thread,
    sketched_thread,
    started_post_id,
    written_post,
)

POSTS = "/api/v1/posts"
BRIEFS = "/api/v1/briefs"
USAGE = "/api/v1/usage"
BRIEF = (
    "Five things I learned shipping every week for a year: ship on Fridays, keep a public "
    "changelog, cut scope not quality, ask one user each week, and never rewrite twice. "
    "Make it a thread."
)
CACHED = {"type": "ephemeral", "ttl": "1h"}
INPUTS = (
    f"<raw_input>\n{BRIEF}\n</raw_input>\n\n"
    f"<positioning>\n{TEXT}\n</positioning>\n\n"
    "<core_idea>\nFive lessons from shipping small things every week.\n</core_idea>\n\n"
    "<takeaway>\nShip the smallest thing that works this week.\n</takeaway>\n\n"
    "<choices>\nfunnel: MOF\ndesired_action: bookmark\nformat: thread\n"
    "structure: hook_list_closer\n</choices>"
)
FINAL = ["Ship on Fridays.", "Keep a public changelog."]


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


async def _write_thread(client, fake_llm, final: list[str] = FINAL, **plan):
    fake_llm.standing[POST_IDEAS] = ideas(planned_thread(**plan))
    fake_llm.replies = [{"parts": final}]
    return await client.post(BRIEFS, json={"brief": BRIEF})


def _calls(fake_llm, schema: type) -> list[LLMCall]:
    return [call for call in fake_llm.calls if call.response_model is schema]


def _system_text(call: LLMCall) -> str:
    [block] = call.messages[0]["content"]
    assert block["cache_control"] == CACHED
    return block["text"]


def _headings(prompt: str) -> list[str]:
    return [line for line in prompt.splitlines() if line.startswith("#")]


def _angle(call: LLMCall) -> str:
    match = re.search(r"around the `(\w+)` hook type", call.messages[1]["content"])
    assert match is not None
    return match.group(1)


async def _version(db) -> VersionAttempt:
    [attempt] = (await db.scalars(select(VersionAttempt))).all()
    return attempt


async def _generations_used(client) -> int:
    return (await client.get(USAGE)).json()["allowance"]["generations"]["used"]


def _plan_prompt(fake_llm) -> str:
    return _system_text(fake_llm.calls[0])


def _planned_shapes(fake_llm) -> list[dict]:
    """The shapes the plan call's answer allows for the single-post plan."""
    schema = fake_llm.calls[0].response_model.model_json_schema()
    refs = schema["properties"]["single_idea"]["anyOf"]
    return [schema["$defs"][ref["$ref"].rsplit("/", 1)[-1]] for ref in refs]


# The planner's choice per account limit


async def test_on_a_280_character_account_the_planner_chooses_a_short_post_or_a_thread(
    client, ready, fake_llm
):
    await _write_thread(client, fake_llm)

    prompt = _plan_prompt(fake_llm)
    assert "A post on my X account holds at most 280 characters." in prompt
    assert "- short: at most 280 characters" in prompt
    assert "- thread: 2 to 10 posts of at most 280 characters each" in prompt
    assert "needs more room than one post on my account holds" in prompt
    assert "- medium:" not in prompt and "- long:" not in prompt
    assert "- format: short or thread.\n" in prompt
    assert "{" not in prompt
    post, thread = _planned_shapes(fake_llm)
    assert post["properties"]["format"]["const"] == "short"
    assert post["properties"]["structure"]["enum"] == ["one_line", "few_lines"]
    assert thread["properties"]["format"]["const"] == "thread"
    assert thread["properties"]["structure"]["enum"] == [
        "hook_list_closer",
        "hook_problem_insight_closer",
        "hook_story_insight_closer",
        "hook_playbook_closer",
    ]


async def test_on_a_premium_account_the_planner_prefers_a_medium_or_long_post_to_a_thread(
    client, ready, fake_llm, premium
):
    await premium()

    await _write_thread(client, fake_llm)

    prompt = _plan_prompt(fake_llm)
    assert "- long: about 400 to 2,000 characters" in prompt
    assert "- thread: 2 to 10 posts of at most 25,000 characters each" in prompt
    assert "prefer a medium or long post to a thread" in prompt
    assert "- format: short, medium, long or thread.\n" in prompt
    post, thread = _planned_shapes(fake_llm)
    assert post["properties"]["format"]["enum"] == ["short", "medium", "long"]
    assert len(post["properties"]["structure"]["enum"]) == 6
    assert "one_line" not in thread["properties"]["structure"]["enum"]


async def test_the_planner_is_told_a_thread_asked_for_in_the_brief_is_followed(
    client, ready, fake_llm
):
    await _write_thread(client, fake_llm)

    prompt = _plan_prompt(fake_llm)
    assert '("make it short", "a list", "as a thread", "ask them to DM me")' in prompt
    assert "Choose it when I ask for a thread" in prompt


async def test_a_thread_planned_short_only_is_refused_by_the_schema(
    client, ready, fake_llm, db, assert_reported_502
):
    fake_llm.standing[POST_IDEAS] = ideas(planned_thread(structure="few_lines"))

    assert_reported_502(await client.post(BRIEFS, json={"brief": BRIEF}))


# A written Thread


async def test_a_thread_plan_writes_a_thread_with_five_sketches_a_merge_and_a_humanizer(
    client, ready, fake_llm
):
    response = await _write_thread(client, fake_llm, final=["Ship—on Fridays.", "Keep a log…"])

    started = await written_post(client, response)
    assert (started["plan"]["format"], started["plan"]["length"]) == ("thread", None)
    assert started["plan"]["structure"] == "hook_list_closer"
    [version] = started["versions"]
    assert (version["format"], version["first_reply"]) == ("thread", False)
    assert [part["text"] for part in version["parts"]] == ["Ship - on Fridays.", "Keep a log..."]
    assert {part["char_limit"] for part in version["parts"]} == {280}
    assert [call.response_model.__name__ for call in fake_llm.calls] == [
        POST_IDEAS,
        *["sketched_thread"] * 5,
        "merged_thread",
        "refined_thread",
    ]
    read = (await client.get(f"{POSTS}/{started['id']}")).json()
    assert read["text"]["format"] == "thread"
    assert [part["text"] for part in read["text"]["parts"]] == [
        "Ship - on Fridays.",
        "Keep a log...",
    ]
    assert await _generations_used(client) == 1


async def test_the_version_stores_the_merged_parts_the_hook_the_cta_and_every_sketch(
    client, db, ready, fake_llm
):
    fake_llm.standing[MERGED_THREAD] = merged_thread(["The hook—here", "The closer"])

    await _write_thread(client, fake_llm)

    version = await _version(db)
    assert (version.format, version.first_reply) == ("thread", False)
    assert version.sketch_parts == ["The hook - here", "The closer"]
    assert version.parts == FINAL
    assert (version.hook_levers, version.hook_types, version.cta_type) == (
        ["proof", "curiosity_gap"],
        ["proof", "number_list"],
        "bookmark",
    )
    assert version.sketches is not None and len(version.sketches) == 5
    assert version.sketches[0]["parts"] == ["A sketched hook.", "A sketched closer."]
    assert version.sketches[0]["angle"] == "proof"
    assert version.merge is not None
    assert version.merge["reasoning"] == "Sketch 1's hook, sketch 2's body."
    assert len(version.merge["reviews"]) == 5


# The assembled thread prompts


async def test_the_thread_sketch_prompt_is_the_shared_guide_with_the_thread_only_sections(
    client, ready, fake_llm
):
    await _write_thread(client, fake_llm, desired_action="sign-up", funnel="BOF")

    sketches = _calls(fake_llm, SKETCHED_THREAD)
    assert len({_system_text(call) for call in sketches}) == 1
    prompt = _system_text(sketches[0])
    assert _headings(prompt) == [
        "# Role",
        "# What you are given",
        "# The raw input is the content",
        "# What a good post does",
        "# Funnel stage: bottom of funnel (BOF)",
        "# Desired action: sign-up",
        "# Format: thread",
        "## Part 1",
        "## The last part",
        "# Structure: hook, list, closer",
        "# The structure across the parts",
        "# The hook",
        "## Psychological levers",
        "## Hook types",
        "## How to craft it",
        "## The hook must be honest",
        "# The lines right after the hook",
        "# The closer and the CTA",
        "## CTAs that fit bottom of funnel",
        "## CTA rules at every stage",
        "# How the lines read",
        "# Never add",
        "# Before you answer, check the thread",
        "# Output",
    ]
    assert prompt.startswith(
        "# Role\n\nYou write one thread on X on my behalf: a chain of posts, each replying to "
        "the one before."
    )
    assert 'In this guide, "the post" means the whole thread.' in prompt
    assert "- Write between 2 and 10 parts." in prompt
    assert "- Each part is at most 280 characters as X counts them" in prompt
    assert "- Part 1 is the hook. It shows alone in the feed" in prompt
    assert "- One point per part." in prompt
    assert "- The closer goes in the last part." in prompt
    assert "A thread has no first reply." in prompt
    assert "- The link goes in the last part, and the closer says what it leads to." in prompt
    assert "a sign-up or waitlist (link in the last part)" in prompt
    assert "- No hashtags and no emoji, unless the raw input asks for it." in prompt
    for post_only in ("first_reply", "first reply under", "Not a thread", "# Format: short"):
        assert post_only not in prompt
    assert "- parts: the thread's parts, in order, one string per part." in prompt
    assert "{" not in prompt


async def test_each_thread_sketch_reads_the_plan_and_tries_a_different_hook_type_first(
    client, ready, fake_llm
):
    await _write_thread(client, fake_llm)

    sketches = _calls(fake_llm, SKETCHED_THREAD)
    assert [_angle(call) for call in sketches] == [
        "proof",
        "curiosity_gap",
        "contrarian",
        "clear_outcome",
        "story",
    ]
    assert sketches[0].messages[1] == {
        "role": "user",
        "content": INPUTS
        + "\n\n<angle>\nSeveral writers are sketching this same thread, each from a different "
        "angle, so I can compare them. Your angle: build the hook in part 1 around the `proof` "
        "hook type (proof), combined with one or two other types. If the raw input can't "
        "support that type honestly, use the closest type that it can support and say so in "
        "hook_reasoning. Everything else in the guide applies unchanged.\n</angle>",
    }


async def test_the_thread_merge_reads_every_sketch_as_numbered_parts_and_the_same_guide(
    client, ready, fake_llm
):
    fake_llm.standing[SKETCHED_THREAD] = lambda call: sketched_thread(
        [f"A {_angle(call)} hook.", "The closer."], hook_types=[_angle(call)]
    )

    await _write_thread(client, fake_llm)

    [merge] = _calls(fake_llm, MERGED_THREAD)
    system = _system_text(merge)
    assert system.startswith(
        "# Role\n\nYou are the editor of one thread on X written on my behalf. 5 writers each "
        "sketched the same thread"
    )
    assert "- sketches: the 5 sketches, numbered, each with its parts numbered." in system
    assert "# The guide the writers followed\n\nThe final sketch must follow it too." in system
    assert "# Format: thread" in system and "# Structure: hook, list, closer" in system
    assert "first_reply" not in system
    assert "- parts: the final sketch's parts, in order, one string per part." in system
    content = merge.messages[1]["content"]
    assert content.startswith(INPUTS + "\n\n<sketches>\n")
    assert (
        '<sketch number="1">\nhook_levers: proof, payoff\nhook_types: proof\n'
        "hook_reasoning: The brief's numbers make the claim believable.\ncta_type: none\n"
        '<part number="1">\nA proof hook.\n</part>\n\n<part number="2">\nThe closer.\n</part>\n'
        "</sketch>"
    ) in content
    assert '<sketch number="5">' in content and "A story hook." in content


async def test_the_thread_humanizer_gets_its_prompt_the_brief_and_plan_then_the_scrubbed_parts(
    client, ready, fake_llm
):
    fake_llm.standing[MERGED_THREAD] = merged_thread(["Ship it—then fix it…", "Done"])

    await _write_thread(client, fake_llm)

    [humanizer] = _calls(fake_llm, HUMANIZED_THREAD)
    system, brief, thread = humanizer.messages
    text = _system_text(humanizer)
    assert text.startswith(
        "# Role\n\nYou rewrite one thread on X on my behalf to make it sound human, removing "
        "any AI-tellers. A thread is a chain of posts, each replying to the one before; each "
        "post in it is a part.\n\nFollow the guidelines below to refine the thread you are "
        "given, removing AI-tellers while preserving the thread's core intent and the explicit "
        "asks in the brief."
    )
    assert "keep between 2 and 10 parts" in text
    assert "- Keep each part at most 280 characters as X counts them" in text
    assert "# Humanization guidelines" in text
    assert "- The hook: part 1 stays the hook." in text
    assert "- The structure (hook_list_closer): keep the order of the parts" in text
    assert "real X posts" not in text and "first_reply" not in text
    assert brief == {
        "role": "user",
        "content": (
            "This is the brief the thread below was written from. Use it only to keep the "
            "rewrite true to what it asks for - its position and any explicit asks. Do not add "
            f"anything from it that the thread does not already say.\n\n<brief>\n{BRIEF}\n"
            "</brief>\n\n<plan>\ncore_idea: Five lessons from shipping small things every week.\n"
            "takeaway: Ship the smallest thing that works this week.\nfunnel: MOF\n"
            "desired_action: bookmark (cta: bookmark)\nformat: thread\n"
            "structure: hook_list_closer\n</plan>"
        ),
    }
    assert thread == {
        "role": "user",
        "content": '<part number="1">\nShip it - then fix it...\n</part>\n\n'
        '<part number="2">\nDone\n</part>',
    }


LINK_RULE = (
    "- When the CTA needs a link, the link goes in the last part too. Use a link only if the "
    "raw input gives one; otherwise write [link] where it goes. A thread has no first reply."
)


async def test_a_thread_without_a_link_in_the_raw_input_writes_link_where_it_goes_and_keeps_it(
    client, ready, fake_llm
):
    await _write_thread(client, fake_llm, desired_action="sign-up", funnel="BOF")

    sketch = _system_text(_calls(fake_llm, SKETCHED_THREAD)[0])
    [merge] = [_system_text(call) for call in _calls(fake_llm, MERGED_THREAD)]
    for prompt in (sketch, merge):
        assert f"## The last part\n\n- The closer goes in the last part.\n{LINK_RULE}" in prompt
    humanizer = _system_text(_calls(fake_llm, HUMANIZED_THREAD)[0])
    assert (
        "- The closer and the CTA: keep them in the last part, with the link if there is one. "
        "Keep a [link] placeholder exactly as it is: I replace it with the link before posting."
    ) in humanizer


@pytest.mark.parametrize(
    ("desired_action", "funnel", "rule"),
    [
        pytest.param(
            "click",
            "MOF",
            "- A native link (another thread, an X Article, my profile, my pinned post) can sit "
            "in any part. An external link goes in the last part, and the closer says what it "
            "leads to.",
            id="click",
        ),
        pytest.param(
            "buy",
            "BOF",
            "- The link goes in the last part, and the closer says what it leads to.",
            id="buy",
        ),
    ],
)
async def test_every_thread_link_rule_puts_the_link_in_the_last_part_with_a_closer_that_names_it(
    client, ready, fake_llm, desired_action, funnel, rule
):
    await _write_thread(client, fake_llm, desired_action=desired_action, funnel=funnel)

    prompt = _system_text(_calls(fake_llm, SKETCHED_THREAD)[0])
    assert rule in prompt
    assert (
        "- An external link goes in the last part, and the closer says what it leads to. A "
        "thread has no first reply."
    ) in prompt
    assert '- "Link below" -> "Everything above is in the repo. It\'s free."' in prompt
    assert "Here it is:" not in prompt


async def test_a_thread_on_a_premium_account_states_the_accounts_limit_per_part(
    client, ready, fake_llm, premium
):
    await premium()

    response = await _write_thread(client, fake_llm)

    [version] = (await written_post(client, response))["versions"]
    assert {part["char_limit"] for part in version["parts"]} == {25000}
    sketch = _system_text(_calls(fake_llm, SKETCHED_THREAD)[0])
    assert "- Each part is at most 25,000 characters as X counts them" in sketch
    humanizer = _system_text(_calls(fake_llm, HUMANIZED_THREAD)[0])
    assert "- Keep each part at most 25,000 characters" in humanizer


async def test_no_thread_prompt_is_a_single_post_prompt(client, ready, fake_llm):
    await _write_thread(client, fake_llm)
    thread_prompts = {
        _system_text(call)
        for schema in (SKETCHED_THREAD, MERGED_THREAD, HUMANIZED_THREAD)
        for call in _calls(fake_llm, schema)
    }
    fake_llm.calls.clear()
    fake_llm.standing[POST_IDEAS] = ideas(planned_post())
    fake_llm.replies = [{"post": "A post.", "first_reply": None}]

    assert (await client.post(BRIEFS, json={"brief": BRIEF})).status_code == 201

    post_prompts = {_system_text(call) for call in fake_llm.calls[1:]}
    assert len(thread_prompts) == 3 and len(post_prompts) == 3
    assert thread_prompts.isdisjoint(post_prompts)


# The 2 to 10 Part rule

TOO_MANY = [f"part {n}" for n in range(1, THREAD_MAX_PARTS + 2)]


@pytest.mark.parametrize(
    ("merge", "final"),
    [
        pytest.param(["just one"], FINAL, id="merge of one Part"),
        pytest.param(TOO_MANY, FINAL, id="merge over the cap"),
        pytest.param(["one", " ​ "], FINAL, id="merge with a blank Part"),
        pytest.param(FINAL, ["one"], id="humanizer of one Part"),
        pytest.param(FINAL, TOO_MANY, id="humanizer over the cap"),
    ],
)
async def test_a_merge_or_humanizer_reply_outside_the_part_bounds_fails_the_attempt(
    client, db, ready, fake_llm, fake_posthog, merge, final
):
    fake_llm.standing[MERGED_THREAD] = merged_thread(merge)

    response = await _write_thread(client, fake_llm, final=final)

    assert (await written_post(client, response))["writing_state"] == "not_written"
    fake_posthog.capture_exception.assert_called_once()
    attempt = await _version(db)
    assert (attempt.status, attempt.format, attempt.parts) == ("failed", "thread", None)
    assert await _generations_used(client) == 0


async def test_a_thread_of_the_most_parts_allowed_is_kept_whole(client, ready, fake_llm):
    parts = [f"part {n}" for n in range(1, THREAD_MAX_PARTS + 1)]
    fake_llm.standing[MERGED_THREAD] = merged_thread(parts)

    response = await _write_thread(client, fake_llm, final=parts)

    [version] = (await written_post(client, response))["versions"]
    assert [part["text"] for part in version["parts"]] == parts


async def test_a_sketch_outside_the_part_bounds_is_skipped_like_a_failed_sketch(
    client, db, ready, fake_llm
):
    def _contrarian_writes_one_part(call: LLMCall) -> dict:
        if _angle(call) == "contrarian":
            return sketched_thread(["just one"])
        return sketched_thread([f"A {_angle(call)} hook.", "The closer."])

    fake_llm.standing[SKETCHED_THREAD] = _contrarian_writes_one_part
    fake_llm.standing[MERGED_THREAD] = merged_thread(sketches=4)

    response = await _write_thread(client, fake_llm)

    assert response.status_code == 201, response.text
    [merge] = _calls(fake_llm, MERGED_THREAD)
    assert "4 writers each sketched the same thread" in _system_text(merge)
    assert "contrarian" not in merge.messages[1]["content"]
    stored = (await _version(db)).sketches
    assert stored is not None
    assert [sketch.get("merge_number") for sketch in stored] == [1, 2, None, 3, 4]
    out_of_bounds = stored[2]
    assert out_of_bounds["error"] == "The sketch call wrote 1 Parts; a Thread has 2 to 10"
    assert out_of_bounds["out_of_bounds"] is True
    assert out_of_bounds["parts"] == ["just one"]
    assert out_of_bounds["model"] == stored[0]["model"]
    assert out_of_bounds["usage"] == {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
    }


async def test_when_every_sketch_is_outside_the_part_bounds_the_attempt_fails(
    client, db, ready, fake_llm, fake_posthog
):
    fake_llm.standing[SKETCHED_THREAD] = sketched_thread(TOO_MANY)

    response = await _write_thread(client, fake_llm)

    assert (await written_post(client, response))["writing_state"] == "not_written"
    fake_posthog.capture_exception.assert_called_once()
    assert _calls(fake_llm, MERGED_THREAD) == []
    assert (await _version(db)).status == "failed"


async def test_a_failed_thread_humanizer_call_fails_the_attempt(
    client, db, ready, fake_llm, fake_posthog
):
    fake_llm.standing[POST_IDEAS] = ideas(planned_thread())
    fake_llm.replies = [LLMError("acme: APIConnectionError: down")]

    response = await client.post(BRIEFS, json={"brief": BRIEF})
    assert (await written_post(client, response))["writing_state"] == "not_written"
    fake_posthog.capture_exception.assert_called_once()
    assert (await _version(db)).format == "thread"


# Starting a Post takes no Format


async def test_starting_a_post_takes_no_format(client, ready, fake_llm):
    response = await client.post(BRIEFS, json={"brief": BRIEF, "format": "thread"})

    assert response.status_code == 422
    assert fake_llm.calls == []


async def test_start_post_over_mcp_takes_no_format_and_writes_the_thread_the_planner_chose(
    subscribed, mcp, fake_llm
):
    await mcp.call_tool("set_positioning", text=TEXT)
    tools = await mcp.list_tools()
    assert list(tools["start_post"]["inputSchema"]["properties"]) == ["brief"]
    fake_llm.standing[POST_IDEAS] = ideas(planned_thread())
    fake_llm.replies = [{"parts": FINAL}]

    result = await mcp.call_tool("start_post", brief=BRIEF)

    assert result["isError"] is False, result
    post_id = result["structuredContent"]["id"]
    post = (await mcp.call_tool("get_post", post_id=post_id))["structuredContent"]
    assert (post["plan"]["format"], post["plan"]["length"]) == ("thread", None)
    assert [part["text"] for part in post["versions"][0]["parts"]] == FINAL


# Feedback on a Thread: the thread revise call, then the thread humanizer

FINAL_PARTS = '<part number="1">\nShip on Fridays.\n</part>\n\n<part number="2">\nKeep a public changelog.\n</part>'


async def _thread_with_feedback(client, fake_llm, feedback: str = "shorter", **plan):
    post_id = started_post_id(await _write_thread(client, fake_llm, **plan))
    fake_llm.calls.clear()
    fake_llm.replies = [{"parts": ["Fridays.", "Changelog."]}]
    return post_id, await written_version(client, post_id, feedback)


async def test_feedback_on_a_thread_runs_the_thread_revise_call_then_the_thread_humanizer(
    client, ready, fake_llm
):
    _, version = await _thread_with_feedback(client, fake_llm)

    assert (version["number"], version["format"]) == (2, "thread")
    assert [part["text"] for part in version["parts"]] == ["Fridays.", "Changelog."]
    assert [call.response_model for call in fake_llm.calls] == [REVISED_THREAD, HUMANIZED_THREAD]
    assert [call.model for call in fake_llm.calls] == [
        "openai/gpt-6.1-terra",
        "openai/gpt-6.1-terra",
    ]
    assert {call.max_tokens for call in fake_llm.calls} == {20000}


async def test_the_thread_revise_prompt_is_the_revise_rules_around_the_thread_guide(
    client, ready, fake_llm
):
    await _thread_with_feedback(client, fake_llm, desired_action="sign-up", funnel="BOF")

    [revise] = _calls(fake_llm, REVISED_THREAD)
    prompt = _system_text(revise)
    assert _headings(prompt) == [
        "# Role",
        "# What you are given",
        "# How to revise",
        "# The guide the thread follows",
        "# The raw input is the content",
        "# What a good post does",
        "# Funnel stage: bottom of funnel (BOF)",
        "# Desired action: sign-up",
        "# Format: thread",
        "## Part 1",
        "## The last part",
        "# Structure: hook, list, closer",
        "# The structure across the parts",
        "# The hook",
        "## Psychological levers",
        "## Hook types",
        "## How to craft it",
        "## The hook must be honest",
        "# The lines right after the hook",
        "# The closer and the CTA",
        "## CTAs that fit bottom of funnel",
        "## CTA rules at every stage",
        "# How the lines read",
        "# Never add",
        "# Output",
    ]
    assert prompt.startswith(
        "# Role\n\nYou revise one thread on X written on my behalf, from my feedback. A thread "
        "is a chain of posts, each replying to the one before; each post in it is a part."
    )
    assert "- the versions of the thread: after these inputs" in prompt
    assert "- Keep the hook in part 1 as it is unless my feedback asks to change it." in prompt
    assert "(another number of parts from 2 to 10, another CTA or none," in prompt
    assert "- Keep between 2 and 10 parts and each part within the limit" in prompt
    assert "- Each part is at most 280 characters as X counts them" in prompt
    assert (
        "- When my feedback turns a single post into a thread, a first reply under the post has "
        "no place of its own: what it says goes in the last part, with its link or [link] as it "
        "is, unless my feedback says otherwise."
    ) in prompt
    assert "- The link goes in the last part, and the closer says what it leads to." in prompt
    assert "- parts: the thread's parts, in order, one string per part." in prompt
    for post_only in ("first_reply", "Not a thread", "# Format: short", "- post:"):
        assert post_only not in prompt
    assert "{" not in prompt


async def test_the_thread_revise_conversation_is_the_inputs_then_each_version_after_its_feedback(
    client, ready, fake_llm
):
    post_id, _ = await _thread_with_feedback(client, fake_llm)
    fake_llm.replies = [{"parts": ["Fri.", "Log."]}]

    await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": "warmer"})

    [*_, revise] = _calls(fake_llm, REVISED_THREAD)
    assert revise.messages[1:] == [
        {"role": "user", "content": INPUTS},
        {"role": "assistant", "content": FINAL_PARTS},
        {"role": "user", "content": _framed("shorter", 1)},
        {
            "role": "assistant",
            "content": '<part number="1">\nFridays.\n</part>\n\n<part number="2">\nChangelog.\n</part>',
        },
        {"role": "user", "content": _framed("warmer", 2)},
    ]


def _framed(feedback: str, version: int) -> str:
    return (
        f"That was Version {version}.\n\n"
        "Change the thread you just wrote according to this feedback, and change nothing else. "
        "Keep every part the feedback does not ask about exactly as it is, and return the whole "
        f"thread rather than only the part that changed.\n\nThe feedback:\n{feedback}"
    )


async def test_the_thread_revision_humanizer_uses_the_thread_humanizer_prompt(
    client, ready, fake_llm
):
    fake_llm.standing[REVISED_THREAD] = revised_thread(["Ship—Fridays.", "Changelog."])

    await _thread_with_feedback(client, fake_llm)

    [humanizer] = _calls(fake_llm, HUMANIZED_THREAD)
    assert _system_text(humanizer).startswith(
        "# Role\n\nYou rewrite one thread on X on my behalf to make it sound human"
    )
    assert "- The structure (hook_list_closer): keep the order of the parts" in _system_text(
        humanizer
    )
    assert humanizer.messages[1]["content"].startswith(
        "This is the brief the thread below was written from."
    )
    assert humanizer.messages[2:] == [
        {
            "role": "user",
            "content": "This is the thread as I last saw it, before my latest feedback.\n\n"
            f"<previous_thread>\n{FINAL_PARTS}\n</previous_thread>",
        },
        {
            "role": "user",
            "content": "This is my latest feedback on that thread. The thread below already "
            "applies it, so don't apply it again, and don't add, remove or reorder anything to "
            "serve it. If it asks for something your guidelines would undo, keep what it asks "
            "for.\n\n<feedback>\nshorter\n</feedback>",
        },
        {
            "role": "user",
            "content": "This is the thread to rewrite. Return every sentence that is also in the "
            "previous thread exactly as it is in <thread> below, even if it moved. A sentence that "
            "differs only in punctuation counts as unchanged. Apply your guidelines only to the "
            "sentences that are new or reworded, and don't add sentences or ideas the thread "
            "doesn't have.\n\n<thread>\n"
            '<part number="1">\nShip - Fridays.\n</part>\n\n<part number="2">\nChangelog.\n</part>'
            "\n</thread>",
        },
    ]


async def test_feedback_on_a_hand_edited_thread_keeps_the_users_sentences(client, ready, fake_llm):
    post_id = started_post_id(await _write_thread(client, fake_llm))
    edited = ["Ship on Fridays. I mean it!", "Keep a public changelog."]
    assert (await client.put(f"{POSTS}/{post_id}/text", json={"parts": edited})).is_success
    fake_llm.calls.clear()
    fake_llm.replies = [{"parts": ["a", "b"]}]

    await client.post(f"{POSTS}/{post_id}/versions", json={"feedback": "warmer"})

    [revise] = _calls(fake_llm, REVISED_THREAD)
    assert revise.messages[-1]["content"].startswith(
        'That was Version 1. I changed the text to:\n\n<thread>\n<part number="1">\n'
        "Ship on Fridays. I mean it!\n</part>"
    )
    [humanizer] = _calls(fake_llm, HUMANIZED_THREAD)
    assert humanizer.messages[-2]["content"] == (
        "I wrote these sentences myself. Wherever one of them is in the thread below, even with "
        "different punctuation, return it exactly as I wrote it here, even if your guidelines "
        "would change it, unless my latest feedback asks to change it.\n\n"
        "<my_sentences>\n<sentence>I mean it!</sentence>\n</my_sentences>"
    )


async def test_a_thread_version_stores_the_revised_parts_the_reasoning_and_the_cta(
    client, db, ready, fake_llm
):
    fake_llm.standing[REVISED_THREAD] = revised_thread(
        ["Fri—day.", "Log."], reasoning="Cut part 2 down.", cta_type="bookmark"
    )

    await _thread_with_feedback(client, fake_llm)

    second = (await db.scalars(select(VersionAttempt).order_by(VersionAttempt.sequence))).all()[1]
    assert (second.sketch_parts, second.parts) == (
        ["Fri - day.", "Log."],
        ["Fridays.", "Changelog."],
    )
    assert (second.hook_reasoning, second.hook_name, second.cta_type) == (
        "Cut part 2 down.",
        None,
        "bookmark",
    )
    assert second.first_reply is False


async def test_thread_feedback_over_mcp_is_written_from_the_thread_prompts(
    client, ready, fake_llm, mcp
):
    post_id = started_post_id(await _write_thread(client, fake_llm))
    fake_llm.calls.clear()
    fake_llm.replies = [{"parts": ["Fridays.", "Changelog."]}]

    result = await mcp.call_tool("give_feedback", post_id=post_id, feedback="shorter")

    assert result["isError"] is False, result
    assert [call.response_model for call in fake_llm.calls] == [REVISED_THREAD, HUMANIZED_THREAD]
    assert _system_text(fake_llm.calls[0]).startswith("# Role\n\nYou revise one thread on X")
