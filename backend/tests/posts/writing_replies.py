"""The plan, sketch, merge, humanizer and revise calls' scripted replies, for tests that write a Version."""

from typing import Optional

from pumpkit.posts.writing.post_replies import (
    HumanizedPost,
    HumanizedThread,
    MergedSketch,
    MergedThread,
    RevisedPost,
    RevisedThread,
    SketchedPost,
    SketchedThread,
)

POSTS = "/api/v1/posts"

# What `fake_llm.standing` keys its replies by: the plan's schema name, which both of its answer
# classes share, and the writing calls' classes.
POST_IDEAS = "post_ideas"
SKETCHED_POST = SketchedPost
MERGED_SKETCH = MergedSketch
HUMANIZED_POST = HumanizedPost
REVISED_POST = RevisedPost
SKETCHED_THREAD = SketchedThread
MERGED_THREAD = MergedThread
HUMANIZED_THREAD = HumanizedThread
REVISED_THREAD = RevisedThread


def planned_post(
    core_idea: str = "Shipping small things beats planning big ones.", **choices
) -> dict:
    """One planned post as the plan call answers it: a short trust post by default, which any account takes."""
    return {
        "core_idea": core_idea,
        "takeaway": "Ship the smallest thing that works this week.",
        "reasoning": "The brief holds one result with its numbers, which earns trust.",
        "funnel": "MOF",
        "desired_action": "bookmark",
        "format": "short",
        "structure": "few_lines",
        **choices,
    }


def planned_thread(
    core_idea: str = "Five lessons from shipping small things every week.", **choices
) -> dict:
    """One planned Thread as the plan call answers it: a list for trust by default."""
    return planned_post(
        core_idea, **{"format": "thread", "structure": "hook_list_closer", **choices}
    )


# The default `planned_post()` as a Post's response shows its Plan.
PLAN = {
    "core_idea": "Shipping small things beats planning big ones.",
    "takeaway": "Ship the smallest thing that works this week.",
    "funnel": "middle",
    "desired_action": "bookmark",
    "format": "post",
    "length": "short",
    "structure": "few_lines",
}


def ideas(single: Optional[dict] = None, split: Optional[list[dict]] = None) -> dict:
    """The plan call's answer: the single-post plan, and the split plans when there are any."""
    return {
        "reasoning": "The brief holds one idea, so there is no split.",
        "single_idea": single or planned_post(),
        "split_ideas": split,
    }


def sketched(post: str = "A sketch.", **fields) -> dict:
    """One sketch call's answer: a proof hook with no CTA, unless `fields` say otherwise."""
    return {
        "hook_levers": ["proof", "payoff"],
        "hook_types": ["proof"],
        "hook_reasoning": "The brief's numbers make the claim believable.",
        "cta_type": "none",
        "post": post,
        "first_reply": None,
        **fields,
    }


def sketched_thread(parts: Optional[list[str]] = None, **fields) -> dict:
    """One thread sketch call's answer: two Parts with a proof hook and no CTA by default."""
    return {
        "hook_levers": ["proof", "payoff"],
        "hook_types": ["proof"],
        "hook_reasoning": "The brief's numbers make the claim believable.",
        "cta_type": "none",
        "parts": parts or ["A sketched hook.", "A sketched closer."],
        **fields,
    }


def merged_thread(parts: Optional[list[str]] = None, sketches: int = 5, **fields) -> dict:
    """The thread merge call's answer, reviewing `sketches` sketches."""
    reply = merged(sketches=sketches, **fields)
    del reply["post"], reply["first_reply"]
    return {**reply, "parts": parts or ["The merged hook.", "The merged closer."]}


def merged(post: str = "The merged sketch.", sketches: int = 5, **fields) -> dict:
    """The merge call's answer, reviewing `sketches` sketches."""
    return {
        "reviews": [
            {"sketch_number": number, "keep": f"keep {number}", "drop": f"drop {number}"}
            for number in range(1, sketches + 1)
        ],
        "reasoning": "Sketch 1's hook, sketch 2's body.",
        "hook_levers": ["proof", "curiosity_gap"],
        "hook_types": ["proof", "number_list"],
        "cta_type": "bookmark",
        "post": post,
        "first_reply": None,
        **fields,
    }


def revised(post: str = "The revised post.", **fields) -> dict:
    """The revise call's answer: no CTA and no first reply, unless `fields` say otherwise."""
    return {
        "reasoning": "The feedback asks for less; the hook stays.",
        "cta_type": "none",
        "post": post,
        "first_reply": None,
        **fields,
    }


def revised_thread(parts: Optional[list[str]] = None, **fields) -> dict:
    """The thread revise call's answer: two Parts and no CTA, unless `fields` say otherwise."""
    return {
        "reasoning": "The feedback asks for less; part 1 stays.",
        "cta_type": "none",
        "parts": parts or ["The revised hook.", "The revised closer."],
        **fields,
    }


def humanizer_calls(fake_llm) -> list:
    """The humanizer calls the fake model received, a post's or a Thread's."""
    return [
        call for call in fake_llm.calls if call.response_model in (HUMANIZED_POST, HUMANIZED_THREAD)
    ]


async def start_thread(client, fake_llm, parts: list[str], brief: str = "ship small things"):
    """
    Start a Post the planner makes a Thread, whose humanizer writes `parts`. Replies queued before
    stay queued for later calls, and the plan call answers as before afterwards.
    """
    before = fake_llm.standing[POST_IDEAS]
    fake_llm.standing[POST_IDEAS] = ideas(planned_thread())
    fake_llm.replies.insert(0, {"parts": list(parts)})
    try:
        return await client.post(POSTS, json={"brief": brief})
    finally:
        fake_llm.standing[POST_IDEAS] = before


async def written_post(client, response) -> dict:
    """
    The Post a start `response` named, read once its first Version's write has ended, as
    `GET /posts/{id}` answers it. The suite runs the write inside the request.
    """
    assert response.status_code == 201, response.text
    read = await client.get(f"{POSTS}/{response.json()['id']}")
    assert read.status_code == 200, read.text
    return read.json()
