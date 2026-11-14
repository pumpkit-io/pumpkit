"""A Version's text as a model reads it in a message, in the Version's own Format."""

from pumpkit.posts.formats import FORMAT_THREAD, Format


def numbered_parts(parts: list[str]) -> str:
    """A Thread's Parts, numbered so the model can tell them apart and Feedback can name one."""
    return "\n\n".join(
        f'<part number="{number}">\n{text}\n</part>' for number, text in enumerate(parts, start=1)
    )


def tagged_post(post: str, first_reply: str) -> str:
    """A single post and its first reply, tagged so the model can tell them apart, as v5 sends them."""
    return f"<post>\n{post}\n</post>\n\n<first_reply>\n{first_reply}\n</first_reply>"


def format_text(format: Format, parts: list[str], *, first_reply: bool) -> str:
    """A single post as written, or tagged with its first reply; a Thread as its numbered Parts."""
    if format == FORMAT_THREAD:
        return numbered_parts(parts)
    if first_reply:
        post, reply = parts
        return tagged_post(post, reply)
    [text] = parts
    return text
