"""
The writing guide of a Thread's sketch and merge calls: the sections a single post's guide shares
with it, with a Thread's link in its last Part, and the sections only a Thread has. It is new
text, seeded from the pumpkit-v6 thread sketch prompt's rules (ADR 0026).
"""

from pumpkit.posts.plans import Plan
from pumpkit.posts.writing.constants import THREAD_MAX_PARTS, THREAD_MIN_PARTS
from pumpkit.posts.writing.prompts.guide import (
    CONTENT_RULES,
    FUNNEL,
    GOOD_POST,
    HOOK,
    NEVER_ADD,
    OPENING,
    PROMPT_FUNNELS,
    RHYTHM,
    STRUCTURE,
    THREAD_LINKS,
    action_section,
    closer_section,
)


def _format_section(char_limit: int) -> str:
    return f"""\
# Format: thread

A thread is a few posts read in order, each replying to the one before. Each post in it is a part. In this guide, "the post" means the whole thread.

- Write between {THREAD_MIN_PARTS} and {THREAD_MAX_PARTS} parts. Pick how many the material needs, and no part that only repeats or pads. When I say how many parts I want, write that many, within the same bounds.
- Each part is at most {char_limit:,} characters as X counts them (a link counts as 23, an emoji as 2). This is a hard limit: count each part before you answer.
- One point per part. Each part reads on its own as a post and leads into the next one. Don't cut a sentence across two parts.
- No numbering such as "1/7" or "1." and no thread emoji, unless the raw input asks for them.

## Part 1

- Part 1 is the hook. It shows alone in the feed, so it must stand on its own: a reader who sees only part 1 knows what the thread is about and wants the rest.
- Don't spend it on setup. The explanation and the details go in the parts after it.

## The last part

- The closer goes in the last part.
- When the CTA needs a link, the link goes in the last part too. Use a link only if the raw input gives one; otherwise write [link] where it goes. A thread has no first reply."""


STRUCTURE_ACROSS_PARTS = """\
# The structure across the parts

- Part 1: the hook.
- The parts in between: the body of the structure, one point per part (one item, one step, one beat of the story, the problem, the insight). A point too long for one part takes two, split where a sentence ends.
- The last part: the closer, and the CTA if there is one."""


def thread_guide(plan: Plan, char_limit: int) -> str:
    """Everything a writer needs to write this Thread, tailored to the Plan's choices."""
    return "\n\n".join(
        [
            CONTENT_RULES,
            GOOD_POST,
            FUNNEL[PROMPT_FUNNELS[plan.funnel]],
            action_section(plan, THREAD_LINKS),
            _format_section(char_limit),
            STRUCTURE[plan.structure],
            STRUCTURE_ACROSS_PARTS,
            HOOK,
            OPENING,
            closer_section(plan, THREAD_LINKS),
            RHYTHM,
            NEVER_ADD,
        ]
    )
