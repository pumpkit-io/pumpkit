"""Feedback as the revision call is handed it: pumpkit-v6's words, named for the Format."""

from pumpkit.posts.formats import FORMAT_THREAD, Format


def format_noun(format: Format) -> str:
    return "thread" if format == FORMAT_THREAD else "post"


def feedback_message(feedback: str, previous: Format, format: Format) -> str:
    """
    One function for both the new Feedback and the earlier ones rebuilt into the conversation,
    so the model never sees a framing it wasn't sent. `previous` is the Format of the Version the
    Feedback was given on, `format` the one it asks for.
    """
    if previous != format:
        return _switch_message(feedback, format)
    noun = format_noun(format)
    return (
        f"Change the {noun} you just wrote according to this feedback, and change "
        "nothing else. Keep every part the feedback does not ask about exactly "
        f"as it is, and return the whole {noun} rather than only the part that "
        f"changed.\n\nThe feedback:\n{feedback}"
    )


def _switch_message(feedback: str, format: Format) -> str:
    """Written for Pumpkit: a switch can't keep everything as it is, so it keeps the content."""
    if format == FORMAT_THREAD:
        ask = (
            "Rewrite the post you just wrote as a thread, according to this feedback. Keep "
            "what it says and how it says it wherever the feedback does not ask for a change, "
            "spread over the parts the thread needs, and return the whole thread."
        )
    else:
        ask = (
            "Rewrite the thread you just wrote as a single post, according to this feedback. "
            "Keep what it says and how it says it wherever the feedback does not ask for a "
            "change and one post has room for it, and return the whole post."
        )
    return f"{ask}\n\nThe feedback:\n{feedback}"
