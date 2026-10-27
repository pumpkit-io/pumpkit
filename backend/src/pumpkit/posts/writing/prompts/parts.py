"""A Version's text as a model reads it in a message, in the Version's own Format."""

from pumpkit.posts.formats import FORMAT_THREAD, Format


def numbered_parts(parts: list[str]) -> str:
    """A Thread's Parts, numbered so the model can tell them apart and Feedback can name one."""
    return "\n\n".join(
        f'<part number="{number}">\n{text}\n</part>' for number, text in enumerate(parts, start=1)
    )


def format_text(format: Format, parts: list[str]) -> str:
    """A single post as written, a Thread as its numbered Parts."""
    if format == FORMAT_THREAD:
        return numbered_parts(parts)
    [text] = parts
    return text
