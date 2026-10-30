"""
What the humanizer call is handed after Feedback, on top of what pumpkit-v6 sent it.

Written for Pumpkit, not ported: these messages carry the rules so `HUMANIZER_PROMPT` stays v6's.
Each text comes in its own Format, so after a switch the previous Version's text and the Sketch differ.
"""

from pumpkit.posts.formats import Format, format_noun
from pumpkit.posts.writing.prompts.parts import format_text


def earlier_feedback_message(feedback: list[str]) -> str:
    """
    Framed as done and as context only: handed earlier Feedback as standing asks, the humanizer
    applied "write a much longer version" again on every later Version.
    """
    items = "\n".join(f"<feedback>\n{text}\n</feedback>" for text in feedback)
    return (
        "This is the feedback I gave before my latest, oldest first. Each one was applied when I "
        "gave it, so don't apply any of it again. Read it only so the rewrite doesn't undo "
        "something I asked for that still holds, such as a length or a word I don't want.\n\n"
        f"<earlier_feedback>\n{items}\n</earlier_feedback>"
    )


def previous_final_message(format: Format, parts: list[str]) -> str:
    noun = format_noun(format)
    return (
        f"This is the {noun} as I last saw it, before my latest feedback.\n\n"
        f"<previous_{noun}>\n{format_text(format, parts)}\n</previous_{noun}>"
    )


def latest_feedback_message(feedback: str, previous: Format, format: Format) -> str:
    noun = format_noun(format)
    switch = ""
    if previous != format:
        switch = f", including turning the {format_noun(previous)} into a {noun}"
    return (
        f"This is my latest feedback on that {format_noun(previous)}. The {noun} below already "
        f"applies it{switch}, so don't apply it again, and don't add, remove or reorder "
        "anything to serve it. If it asks for something your guidelines would undo, keep what "
        f"it asks for.\n\n<feedback>\n{feedback}\n</feedback>"
    )


def hand_written_message(sentences: list[str], format: Format) -> str:
    """The User's own words outrank the guidelines, as in the Feedback that asked for something."""
    items = "\n".join(f"<sentence>{sentence}</sentence>" for sentence in sentences)
    return (
        "I wrote these sentences myself. Wherever one of them is in the "
        f"{format_noun(format)} below, even with different punctuation, return it exactly as I "
        "wrote it here, even if your guidelines would change it, unless my latest feedback asks "
        f"to change it.\n\n<my_sentences>\n{items}\n</my_sentences>"
    )


def revised_sketch_message(previous: Format, format: Format, sketch_parts: list[str]) -> str:
    """
    Punctuation alone doesn't count as a change: the scrub runs on the Sketch, not the Version's
    text, so a sentence the User left alone can differ from the previous Version's text in a
    quote or a dash.
    """
    noun = format_noun(format)
    return (
        f"This is the {noun} to rewrite. Return every sentence that is also in the previous "
        f"{format_noun(previous)} exactly as it is in <{noun}> below, even if it moved. A "
        "sentence that differs only in punctuation counts as unchanged. Apply your guidelines "
        "only to the sentences that are new or reworded, and don't add sentences or ideas the "
        f"{noun} doesn't have.\n\n"
        f"<{noun}>\n{format_text(format, sketch_parts)}\n</{noun}>"
    )
