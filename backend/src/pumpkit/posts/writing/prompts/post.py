"""
The sketch, merge and humanizer calls that write a single post's first Version, ported from
pumpkit-new-architecture-v5, and the inputs a Thread's calls share with them (`thread.py`). The
writing guide they share is in `guide.py`.
"""

from dataclasses import dataclass
from typing import Optional, Sequence

from pumpkit.posts.plans import Plan
from pumpkit.posts.writing.constants import HOOK_TYPE_ROTATION
from pumpkit.posts.writing.post_replies import HookType, SketchedPost
from pumpkit.posts.writing.prompts.guide import (
    ACTION,
    PROMPT_FUNNELS,
    char_limit_for_plan,
    effective_length,
    plan_structure,
    prompt_format,
    writing_guide,
)
from pumpkit.posts.writing.prompts.humanizer import HUMANIZATION_GUIDELINES
from pumpkit.posts.writing.prompts.parts import tagged_post


@dataclass(frozen=True)
class PostInputs:
    """What every call writes the post or Thread from: the Brief, the Positioning and the Idea's Plan."""

    brief: str
    positioning: str
    plan: Plan
    # The post limit of the User's X account.
    char_limit: int


GIVEN = """\
# What you are given

- raw_input: my raw idea. It is the only source of facts. It can hold more than this post's idea: when it does, use only what belongs to the core idea below.
- positioning: who I am on X, what I post about and who I write for. The reader of the post is the audience it names.
- core_idea: the one idea the post delivers.
- takeaway: what the reader walks away with.
- funnel, desired_action, format, structure: the kind of post this is, already decided. The guide below is already tailored to them."""

HOOK_FIELDS = """\
- hook_levers: the one to three psychological levers the hook pulls. Choose these first.
- hook_types: the one to three hook types the hook combines.
- hook_reasoning: one to three sentences, written before the post: why these levers and types fit this idea and this reader, and what question the hook raises in the reader's mind.
- cta_type: the CTA the post makes, or "none"."""

SKETCH_FIELDS = (
    HOOK_FIELDS
    + """
- post: the post text and nothing else. No preamble, no quotes around it, no notes. Line breaks as they should appear on X.
- first_reply: the text of my first reply under the post, only when the CTA needs an external link or a follow-up there. When the CTA needs a link, the first reply holds it: the link the raw input gives, or [link] where it goes if it gives none. null in every other case."""
)


def post_inputs_block(inputs: PostInputs) -> str:
    """The inputs of the sketch and merge calls, a single post's or a Thread's, as the model reads them."""
    plan = inputs.plan
    structure = plan_structure(plan)
    return (
        f"<raw_input>\n{inputs.brief.strip()}\n</raw_input>\n\n"
        f"<positioning>\n{inputs.positioning.strip()}\n</positioning>\n\n"
        f"<core_idea>\n{plan.core_idea.strip()}\n</core_idea>\n\n"
        f"<takeaway>\n{plan.takeaway.strip()}\n</takeaway>\n\n"
        "<choices>\n"
        f"funnel: {PROMPT_FUNNELS[plan.funnel]}\n"
        f"desired_action: {plan.desired_action}\n"
        f"format: {prompt_format(plan)}\n"
        + (f"structure: {structure}\n" if structure else "")
        + "</choices>"
    )


def sketch_prompt(inputs: PostInputs) -> str:
    return f"""\
# Role

You write one post on X on my behalf.

{GIVEN}

{writing_guide(inputs.plan, inputs.char_limit)}

# Before you answer, check the post

- Would the hook make my reader stop scrolling? Does it raise a question they need answered?
- Does the post answer that question and deliver the takeaway?
- Is it one idea? Is every fact in the raw input?
- Does it follow the structure and fit the format's length?
- Is there at most one CTA, and does it fit the desired action?

# Output

One post. Not a thread, not two options, not a post plus an explanation.

{SKETCH_FIELDS}
"""


HOOK_TYPE_NAMES: dict[HookType, str] = {
    "proof": "proof",
    "curiosity_gap": "curiosity gap",
    "contrarian": "contrarian",
    "clear_outcome": "clear outcome",
    "story": "story",
    "bold_claim": "bold claim",
    "number_list": "number / list",
    "callout": "callout",
}


def sketch_angle(index: int) -> HookType:
    """The hook type sketch `index` (from 0) is asked to try first."""
    return HOOK_TYPE_ROTATION[index % len(HOOK_TYPE_ROTATION)]


def angle_block(angle: HookType, *, noun: str, hook: str) -> str:
    """The hook type one of the sketches is asked to try first, in the words of its Format."""
    return (
        "<angle>\n"
        f"Several writers are sketching this same {noun}, each from a different angle, so I can compare them. "
        f"Your angle: build {hook} around the `{angle}` hook type ({HOOK_TYPE_NAMES[angle]}), combined with one or two other types. "
        "If the raw input can't support that type honestly, use the closest type that it can support and say so in hook_reasoning. "
        "Everything else in the guide applies unchanged.\n"
        "</angle>"
    )


def sketch_user(inputs: PostInputs, angle: HookType) -> str:
    return post_inputs_block(inputs) + "\n\n" + angle_block(angle, noun="post", hook="the hook")


def merge_prompt(inputs: PostInputs, sketch_count: int) -> str:
    return f"""\
# Role

You are the editor of one post on X written on my behalf. {sketch_count} writers each sketched the same post from the same inputs and the same guide. You produce the one sketch that gets published: it takes the best of each sketch and leaves out what is bad in them.

{GIVEN}
- sketches: the {sketch_count} sketches, numbered. Each has the levers and hook types its writer chose, their reasoning, the post, and sometimes a first reply.

# How to merge

1. Review each sketch as my reader would meet it in the feed: someone from the audience in my positioning, scrolling fast. For each one note what to keep (a hook, a line, a transition, a closer, an order of ideas) and what to drop.
2. Choose the hook. Read only the first lines of each sketch and ask: which one makes this reader stop and read line two, and raises a question they need answered? It must be honest: the post has to deliver what it promises. You can sharpen the winning hook with a detail or a phrase from another sketch.
3. Choose the body. Take the clearest telling of each part of the structure. When two sketches say the same thing, keep the more specific, shorter one.
4. Choose the closer and the one CTA that fits the desired action, or no CTA.
5. Write the final sketch as one post in one voice. It must read as if one person typed it in one go, not as lines stitched together. Rewrite the joins. The line after the hook moves forward and doesn't repeat it.

# What to remove

- Any fact, number, name, link or claim that is not in the raw input or the positioning, even if several sketches have it.
- Clickbait: a hook the post doesn't pay off.
- Anything off the core idea. A good line about a second idea still goes.
- Lines that repeat an earlier line in other words. Warm-up. Recaps. Filler.
- A second CTA. Generic engagement bait. Pushy self-promotion.
- Anything that sounds AI-generated: stock hook openers, "it's not X, it's Y", neat triplets, slogans, pseudo-profound closers, every sentence on its own line.
- Anything that breaks the format, the structure or the length limit in the guide.

Do not average the sketches. A merged post that is longer than the best sketch needs a reason: more is not better. If one sketch is clearly the best as it stands, keep it and fix only its weak lines.

# The guide the writers followed

The final sketch must follow it too.

{writing_guide(inputs.plan, inputs.char_limit)}

# Output

- reviews: one entry per sketch, in order. sketch_number; keep: what is worth taking from it, quoting the lines; drop: what is wrong with it.
- reasoning: written before the final sketch, after the reviews. Go through the final post piece by piece, in order: the hook, each part of the structure, the closer and the CTA. For each piece say which sketch (by number) it comes from, quote the lines you take, and say why they beat the same piece in the other sketches. Then say how the pieces join into one voice: what you reword at the joins, what you cut so nothing repeats, and what the total length comes to against the format's limit.
- hook_levers, hook_types, cta_type: as they are in the final sketch.
- post: the final sketch's text and nothing else. No preamble, no quotes around it, no notes. Line breaks as they should appear on X.
- first_reply: the text of my first reply under the post, only when the CTA needs an external link or a follow-up there. When the CTA needs a link, the first reply holds it: the link the raw input gives, or [link] where it goes if it gives none. null in every other case.
"""


def sketches_block(sketches: Sequence[SketchedPost]) -> str:
    parts = []
    for number, sketch in enumerate(sketches, start=1):
        reply = (
            f"\n<first_reply>\n{sketch.first_reply.strip()}\n</first_reply>"
            if sketch.first_reply
            else ""
        )
        parts.append(
            f'<sketch number="{number}">\n'
            f"hook_levers: {', '.join(sketch.hook_levers)}\n"
            f"hook_types: {', '.join(sketch.hook_types)}\n"
            f"hook_reasoning: {sketch.hook_reasoning.strip()}\n"
            f"cta_type: {sketch.cta_type}\n"
            f"<post>\n{sketch.post.strip()}\n</post>{reply}\n"
            "</sketch>"
        )
    return "<sketches>\n" + "\n\n".join(parts) + "\n</sketches>"


def merge_user(inputs: PostInputs, sketches: Sequence[SketchedPost]) -> str:
    return post_inputs_block(inputs) + "\n\n" + sketches_block(sketches)


# Pumpkit's humanizer prompt minus the corpus, plus what the earlier calls decided on purpose.
def humanizer_prompt(inputs: PostInputs) -> str:
    limit = char_limit_for_plan(inputs.plan, inputs.char_limit)
    return (
        """\
# Role

You rewrite one post on X on my behalf to make it sound human, removing any AI-tellers.

Follow the guidelines below to refine the post you are given, removing AI-tellers while preserving the post's core intent and the explicit asks in the brief.

"""
        + HUMANIZATION_GUIDELINES
        + f"""\
# What to preserve

The post you are given was planned on purpose. The brief lists the plan. Removing AI-tellers must not undo it.

- The hook: keep what it promises, its specifics and its place at the top. Reword it only where the wording itself is an AI-teller. Don't flatten it into a plain statement that no longer makes a reader stop.
- The structure ({inputs.plan.structure}): keep the order of the parts and the line breaks that carry it. One thought per line in short paragraphs is intended here; merge lines only where every sentence sits alone between blank lines.
- The closer and the CTA: keep the one specific ask the post makes, if it makes one. Remove an ask only if it is generic engagement bait.
- The first reply: keep a link or a [link] placeholder in it exactly as it is: I replace [link] with the link before posting.
- The facts: every number, name and claim stays as it is. Add none.
- The length: at most {limit:,} characters as X counts them (a link counts as 23). Don't make the post longer than it is.

# Output

- post: the rewritten post text and nothing else - no preamble, no quotes around it, no notes about what you changed.
- first_reply: the rewritten first reply, if one was given with the post, with its link or [link] exactly as it is. null otherwise.
"""
    )


def brief_message(inputs: PostInputs) -> str:
    """The brief, framed as what the rewrite must stay true to rather than more text to rewrite."""
    plan = inputs.plan
    cta = ACTION[plan.desired_action]["cta"]
    return (
        "This is the brief the post below was written from. Use it only to "
        "keep the rewrite true to what it asks for - its position and any "
        "explicit asks. Do not add anything from it that the post does not "
        "already say.\n\n"
        f"<brief>\n{inputs.brief.strip()}\n</brief>\n\n"
        "<plan>\n"
        f"core_idea: {plan.core_idea.strip()}\n"
        f"takeaway: {plan.takeaway.strip()}\n"
        f"funnel: {PROMPT_FUNNELS[plan.funnel]}\n"
        f"desired_action: {plan.desired_action} (cta: {cta})\n"
        f"format: {effective_length(plan)}\n"
        f"structure: {plan.structure}\n"
        "</plan>"
    )


def post_message(post: str, first_reply: Optional[str]) -> str:
    """The post as the app sends it: bare. With a first reply, both are tagged so they can be told apart."""
    if not first_reply:
        return post
    return tagged_post(post, first_reply)
