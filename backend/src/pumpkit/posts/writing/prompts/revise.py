"""
The revise calls and the revision humanizers' messages that write a post's or a Thread's next
Version from Feedback, in the Format the Feedback asks for. A single post's are ported from
pumpkit-new-architecture-v5; a Thread's revise prompt is new text, assembled from v5's revise
prompt and the Thread's guide. The Feedback framings and the hand-written sentences message stay
Pumpkit's (`feedback.py`, `revision_humanizer.py`).
"""

from typing import Optional

from pumpkit.posts.formats import FORMAT_THREAD, Format, format_noun
from pumpkit.posts.writing.constants import THREAD_MAX_PARTS, THREAD_MIN_PARTS
from pumpkit.posts.writing.prompts.guide import writing_guide
from pumpkit.posts.writing.prompts.post import GIVEN, PostInputs
from pumpkit.posts.writing.prompts.revision_humanizer import previous_final_message
from pumpkit.posts.writing.prompts.thread import PARTS_FIELD
from pumpkit.posts.writing.prompts.thread_guide import thread_guide


def revise_prompt(inputs: PostInputs) -> str:
    return f"""\
# Role

You revise one post on X written on my behalf, from my feedback.

{GIVEN}
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

{writing_guide(inputs.plan, inputs.char_limit)}

# Output

- reasoning: written before the post, in two to five sentences: what my feedback asks for, which lines change and how, and what stays as it is. When you write a new hook, name the levers and hook types you chose and the question the hook raises in the reader's mind.
- cta_type: the CTA the revised post makes, or "none".
- post: the whole revised post and nothing else. No preamble, no quotes around it, no notes about what you changed. Line breaks as they should appear on X.
- first_reply: the text of my first reply under the post, only when the CTA needs an external link or a follow-up there. Keep the one the latest version has unless my feedback changes it. Use a link only if the raw input or my feedback gives one; otherwise write [link] where it goes. null in every other case.
"""


def thread_revise_prompt(inputs: PostInputs) -> str:
    return f"""\
# Role

You revise one thread on X written on my behalf, from my feedback. A thread is a chain of posts, each replying to the one before; each post in it is a part.

{GIVEN}
- the versions of the thread: after these inputs, the conversation holds each version, numbered from Version 1, each followed by my feedback on it. A version is a single post when my feedback turned it into one, or before my feedback turned it into a thread. The last message is my latest feedback, on the latest version.

# How to revise

- Do what my latest feedback asks, and only that. Every part and every line it doesn't ask about stays word for word, in its place. Return the whole thread, every part, not only the part that changed.
- Keep the hook in part 1 as it is unless my feedback asks to change it. One exception: when the change leaves the hook promising something the thread no longer delivers, fix the hook so it stays honest, and change as little of it as you can.
- The feedback is mine, so it wins. Where it goes against the choices or the guide below (another number of parts from {THREAD_MIN_PARTS} to {THREAD_MAX_PARTS}, another CTA or none, another structure, a word or a line I want), do what it asks.
- Everything you write new follows the guide. For a new hook, choose the levers, then the hook types, then write it, as the hook section says. A new closer or CTA follows the closer and CTA section. New lines follow "How the lines read" and "Never add".
- A fact, number, name or link I give in the feedback counts as if it were in the raw input. Invent no others.
- My earlier feedback still holds. Don't undo what it asked for unless my latest feedback asks to.
- When the feedback is vague ("make it punchier", "I don't like the ending"), change the smallest part of the thread that answers it.
- Keep between {THREAD_MIN_PARTS} and {THREAD_MAX_PARTS} parts and each part within the limit, whatever my feedback asks.
- When my feedback turns a single post into a thread, a first reply under the post has no place of its own: what it says goes in the last part, with its link or [link] as it is, unless my feedback says otherwise.
- The revised thread still reads as if one person typed it in one go. Where a new line meets an old one, reword the join only as much as it needs.

# The guide the thread follows

What you write new must follow it too.

{thread_guide(inputs.plan, inputs.char_limit)}

# Output

- reasoning: written before the thread, in two to five sentences: what my feedback asks for, which parts and lines change and how, and what stays as it is. When you write a new hook, name the levers and hook types you chose and the question the hook raises in the reader's mind.
- cta_type: the CTA the revised thread makes, or "none".
{PARTS_FIELD}
"""


def previous_message(format: Format, parts: list[str], *, first_reply: bool) -> str:
    """The text the latest Feedback was given on, in its own Format, for a revision humanizer."""
    if format == FORMAT_THREAD:
        return previous_final_message(format, parts, first_reply=False)
    return previous_post_message(parts[0], parts[-1] if first_reply else None)


def previous_post_message(post: str, first_reply: Optional[str]) -> str:
    reply = (
        f"\n\n<previous_first_reply>\n{first_reply}\n</previous_first_reply>" if first_reply else ""
    )
    return (
        "This is the post as I last saw it, before my latest feedback.\n\n"
        f"<previous_post>\n{post}\n</previous_post>{reply}"
    )


def revised_post_message(post: str, first_reply: Optional[str], previous: Format) -> str:
    reply = f"\n\n<first_reply>\n{first_reply}\n</first_reply>" if first_reply else ""
    return (
        "This is the post to rewrite. Return every sentence that is also in the previous "
        f"{format_noun(previous)} exactly as it is in <post> below, even if it moved. A sentence that differs only in "
        "punctuation counts as unchanged. Apply your guidelines only to the sentences that are "
        "new or reworded, and don't add sentences or ideas the post doesn't have.\n\n"
        f"<post>\n{post}\n</post>{reply}"
    )
