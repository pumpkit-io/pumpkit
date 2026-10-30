"""
Feedback as the revision call is handed it: pumpkit-v6's words, named for the Format, after the
number of the Version it follows and what the User did to the Text before sending it (ADR 0016).
"""

from typing import Optional

from pumpkit.posts.formats import FORMAT_THREAD, Format, format_noun
from pumpkit.posts.writing.prompts.parts import format_text


def feedback_message(feedback: str, after: int, previous: Format, format: Format) -> str:
    """
    Feedback on the Version just written, as written. One function for both the new Feedback and
    the earlier ones rebuilt into the conversation, like the two below, so the model never sees a
    framing it wasn't sent. `previous` is the Format the Feedback was given on, `format` the one
    it asks for.
    """
    subject = f"the {format_noun(previous)} you just wrote"
    return f"That was Version {after}.\n\n{_ask(feedback, subject, previous, format)}"


def went_back_message(
    feedback: str, after: int, back_to: int, previous: Format, format: Format
) -> str:
    """Feedback on an earlier Version, which the User went back to as it was written."""
    ask = _ask(feedback, f"Version {back_to}", previous, format)
    return f"That was Version {after}. I went back to Version {back_to}.\n\n{ask}"


def changed_message(
    feedback: str,
    after: int,
    began_from: Optional[int],
    previous: Format,
    parts: list[str],
    format: Format,
) -> str:
    """
    Feedback on a Text the User changed by hand, from the Version just written or, with
    `began_from`, from an earlier one they went back to first.
    """
    noun = format_noun(previous)
    went_back = (
        "I changed the text to:"
        if began_from is None
        else f"I went back to Version {began_from} and changed it to:"
    )
    ask = _ask(feedback, f"my {noun} above", previous, format)
    return (
        f"That was Version {after}. {went_back}\n\n"
        f"<{noun}>\n{format_text(previous, parts)}\n</{noun}>\n\n{ask}"
    )


def _ask(feedback: str, subject: str, previous: Format, format: Format) -> str:
    if previous != format:
        return _switch_message(feedback, subject, format)
    noun = format_noun(format)
    return (
        f"Change {subject} according to this feedback, and change "
        "nothing else. Keep every part the feedback does not ask about exactly "
        f"as it is, and return the whole {noun} rather than only the part that "
        f"changed.\n\nThe feedback:\n{feedback}"
    )


def _switch_message(feedback: str, subject: str, format: Format) -> str:
    """Written for Pumpkit: a switch can't keep everything as it is, so it keeps the content."""
    if format == FORMAT_THREAD:
        ask = (
            f"Rewrite {subject} as a thread, according to this feedback. Keep "
            "what it says and how it says it wherever the feedback does not ask for a change, "
            "spread over the parts the thread needs, and return the whole thread."
        )
    else:
        ask = (
            f"Rewrite {subject} as a single post, according to this feedback. "
            "Keep what it says and how it says it wherever the feedback does not ask for a "
            "change and one post has room for it, and return the whole post."
        )
    return f"{ask}\n\nThe feedback:\n{feedback}"
