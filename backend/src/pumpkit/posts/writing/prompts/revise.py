"""
The revise call and the revision humanizer's messages that write a single post's next Version from
Feedback, ported from pumpkit-new-architecture-v5. The Feedback framings and the hand-written
sentences message stay Pumpkit's (`feedback.py`, `revision_humanizer.py`).
"""

from typing import Optional

from pumpkit.posts.writing.prompts.guide import writing_guide
from pumpkit.posts.writing.prompts.post import GIVEN, PostInputs


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


def previous_post_message(post: str, first_reply: Optional[str]) -> str:
    reply = (
        f"\n\n<previous_first_reply>\n{first_reply}\n</previous_first_reply>" if first_reply else ""
    )
    return (
        "This is the post as I last saw it, before my latest feedback.\n\n"
        f"<previous_post>\n{post}\n</previous_post>{reply}"
    )


def revised_post_message(post: str, first_reply: Optional[str]) -> str:
    reply = f"\n\n<first_reply>\n{first_reply}\n</first_reply>" if first_reply else ""
    return (
        "This is the post to rewrite. Return every sentence that is also in the previous post "
        "exactly as it is in <post> below, even if it moved. A sentence that differs only in "
        "punctuation counts as unchanged. Apply your guidelines only to the sentences that are "
        "new or reworded, and don't add sentences or ideas the post doesn't have.\n\n"
        f"<post>\n{post}\n</post>{reply}"
    )
