"""
The sketch, merge and humanizer calls that write a Thread's first Version. New text, assembled
from the sections a single post's calls share with it (`post.py`, `guide.py`) and a Thread's own:
no prompt here serves a single post, and none in `post.py` serves a Thread.
"""

from typing import Sequence

from pumpkit.posts.writing.constants import THREAD_MAX_PARTS, THREAD_MIN_PARTS
from pumpkit.posts.writing.post_replies import HookType, SketchedThread
from pumpkit.posts.writing.prompts.guide import ACTION, PROMPT_FUNNELS
from pumpkit.posts.writing.prompts.humanizer import HUMANIZATION_GUIDELINES
from pumpkit.posts.writing.prompts.parts import numbered_parts
from pumpkit.posts.writing.prompts.post import (
    GIVEN,
    HOOK_FIELDS,
    PostInputs,
    angle_block,
    post_inputs_block,
)
from pumpkit.posts.writing.prompts.thread_guide import thread_guide

PARTS_FIELD = """\
- parts: the thread's parts, in order, one string per part. Each holds the part's text and nothing else: no preamble, no quotes around it, no number label, no notes. Line breaks as they should appear on X."""


def thread_sketch_prompt(inputs: PostInputs) -> str:
    return f"""\
# Role

You write one thread on X on my behalf: a chain of posts, each replying to the one before.

{GIVEN}

{thread_guide(inputs.plan, inputs.char_limit)}

# Before you answer, check the thread

- Would part 1 alone make my reader stop scrolling? Does it raise a question they need answered?
- Does the thread answer that question and deliver the takeaway?
- Is it one idea, with one point per part? Is every fact in the raw input?
- Does it follow the structure, in {THREAD_MIN_PARTS} to {THREAD_MAX_PARTS} parts, each within the limit?
- Is there at most one CTA, in the last part, and does it fit the desired action?

# Output

One thread. Not a single post, not two options, not a thread plus an explanation.

{HOOK_FIELDS}
{PARTS_FIELD}
"""


def thread_sketch_user(inputs: PostInputs, angle: HookType) -> str:
    return (
        post_inputs_block(inputs)
        + "\n\n"
        + angle_block(angle, noun="thread", hook="the hook in part 1")
    )


def thread_merge_prompt(inputs: PostInputs, sketch_count: int) -> str:
    return f"""\
# Role

You are the editor of one thread on X written on my behalf. {sketch_count} writers each sketched the same thread from the same inputs and the same guide. You produce the one sketch that gets published: it takes the best of each sketch and leaves out what is bad in them.

{GIVEN}
- sketches: the {sketch_count} sketches, numbered, each with its parts numbered. Each has the levers and hook types its writer chose, their reasoning, and the thread.

# How to merge

1. Review each sketch as my reader would meet it in the feed: someone from the audience in my positioning, scrolling fast, who sees part 1 alone. For each one note what to keep (a hook, a part, a line, a transition, a closer, an order of ideas) and what to drop.
2. Choose the hook. Read only part 1 of each sketch and ask: which one makes this reader stop and open the thread, and raises a question they need answered? It must be honest: the thread has to deliver what it promises. You can sharpen the winning hook with a detail or a phrase from another sketch.
3. Choose the body. Take the clearest telling of each part of the structure, one point per part. When two sketches say the same thing, keep the more specific, shorter one.
4. Choose the closer and the one CTA that fits the desired action, or no CTA. Both go in the last part.
5. Write the final sketch as one thread in one voice. It must read as if one person typed it in one go, not as parts stitched together. Rewrite the joins. Part 2 moves forward and doesn't repeat the hook.

# What to remove

- Any fact, number, name, link or claim that is not in the raw input or the positioning, even if several sketches have it.
- Clickbait: a hook the thread doesn't pay off.
- Anything off the core idea. A good part about a second idea still goes.
- Parts or lines that repeat an earlier one in other words. Warm-up. Recaps. Filler.
- A second CTA. Generic engagement bait. Pushy self-promotion.
- Anything that sounds AI-generated: stock hook openers, "it's not X, it's Y", neat triplets, slogans, pseudo-profound closers, every sentence on its own line.
- Anything that breaks the structure, the {THREAD_MIN_PARTS} to {THREAD_MAX_PARTS} parts or a part's length limit in the guide.

Do not average the sketches. A merged thread with more parts than the best sketch needs a reason: more is not better. If one sketch is clearly the best as it stands, keep it and fix only its weak lines.

# The guide the writers followed

The final sketch must follow it too.

{thread_guide(inputs.plan, inputs.char_limit)}

# Output

- reviews: one entry per sketch, in order. sketch_number; keep: what is worth taking from it, quoting the lines; drop: what is wrong with it.
- reasoning: written before the final sketch, after the reviews. Go through the final thread part by part, in order: the hook, each part of the structure, the closer and the CTA. For each part say which sketch (by number) it comes from, quote the lines you take, and say why they beat the same part in the other sketches. Then say how the parts join into one voice: what you reword at the joins, what you cut so nothing repeats, and how many parts there are, each against the limit.
- hook_levers, hook_types, cta_type: as they are in the final sketch.
- parts: the final sketch's parts, in order, one string per part. Each holds the part's text and nothing else: no preamble, no quotes around it, no number label, no notes. Line breaks as they should appear on X.
"""


def thread_sketches_block(sketches: Sequence[SketchedThread]) -> str:
    blocks = []
    for number, sketch in enumerate(sketches, start=1):
        parts = numbered_parts([part.strip() for part in sketch.parts])
        blocks.append(
            f'<sketch number="{number}">\n'
            f"hook_levers: {', '.join(sketch.hook_levers)}\n"
            f"hook_types: {', '.join(sketch.hook_types)}\n"
            f"hook_reasoning: {sketch.hook_reasoning.strip()}\n"
            f"cta_type: {sketch.cta_type}\n"
            f"{parts}\n"
            "</sketch>"
        )
    return "<sketches>\n" + "\n\n".join(blocks) + "\n</sketches>"


def thread_merge_user(inputs: PostInputs, sketches: Sequence[SketchedThread]) -> str:
    return post_inputs_block(inputs) + "\n\n" + thread_sketches_block(sketches)


def thread_humanizer_prompt(inputs: PostInputs) -> str:
    limit = inputs.char_limit
    return (
        f"""\
# Role

You rewrite one thread on X on my behalf to make it sound human, removing any AI-tellers. A thread is a chain of posts, each replying to the one before; each post in it is a part.

Follow the guidelines below to refine the thread you are given, removing AI-tellers while preserving the thread's core intent and the explicit asks in the brief.

The thread you are given has its parts numbered in <part> tags. Rewrite each part in place:

- Keep the parts and their order. Merge or split parts only when the guidelines leave no other fix, and keep between {THREAD_MIN_PARTS} and {THREAD_MAX_PARTS} parts.
- Keep each part at most {limit:,} characters as X counts them: a link counts as 23, an emoji as 2.
- Do not add numbering such as "1/7" or a thread emoji unless the brief asks for them, and keep them if it does.
- Apply the guidelines to the thread as a whole too: a pattern repeated across parts is clustered.

"""
        + HUMANIZATION_GUIDELINES
        + f"""\
# What to preserve

The thread you are given was planned on purpose. The brief lists the plan. Removing AI-tellers must not undo it.

- The hook: part 1 stays the hook. Keep what it promises and its specifics, and keep it standing on its own in the feed. Reword it only where the wording itself is an AI-teller. Don't flatten it into a plain statement that no longer makes a reader stop.
- The structure ({inputs.plan.structure}): keep the order of the parts, one point per part, and the line breaks that carry it.
- The closer and the CTA: keep them in the last part, with the link if there is one. Keep the one specific ask the thread makes, if it makes one. Remove an ask only if it is generic engagement bait.
- The facts: every number, name and claim stays as it is. Add none.
- The length: each part at most {limit:,} characters as X counts them (a link counts as 23). Don't make the thread longer than it is.

# Output

- parts: the rewritten parts in order, one string per part, each holding the part's text and nothing else: no preamble, no quotes around it, no <part> tags, no number label, no notes about what you changed.
"""
    )


def thread_brief_message(inputs: PostInputs) -> str:
    """The brief, framed as what the rewrite must stay true to rather than more text to rewrite."""
    plan = inputs.plan
    cta = ACTION[plan.desired_action]["cta"]
    return (
        "This is the brief the thread below was written from. Use it only to "
        "keep the rewrite true to what it asks for - its position and any "
        "explicit asks. Do not add anything from it that the thread does not "
        "already say.\n\n"
        f"<brief>\n{inputs.brief.strip()}\n</brief>\n\n"
        "<plan>\n"
        f"core_idea: {plan.core_idea.strip()}\n"
        f"takeaway: {plan.takeaway.strip()}\n"
        f"funnel: {PROMPT_FUNNELS[plan.funnel]}\n"
        f"desired_action: {plan.desired_action} (cta: {cta})\n"
        "format: thread\n"
        f"structure: {plan.structure}\n"
        "</plan>"
    )


def thread_message(parts: list[str]) -> str:
    return numbered_parts(parts)
