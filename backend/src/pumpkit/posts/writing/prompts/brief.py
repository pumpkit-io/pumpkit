"""The Brief as the humanizer call is handed it, word for word from pumpkit-v6."""

from pumpkit.posts.formats import FORMAT_THREAD, Format


def brief_message(brief: str, format: Format) -> str:
    """The Brief, framed as what the rewrite must stay true to rather than more text to rewrite."""
    text = "thread" if format == FORMAT_THREAD else "post"
    return (
        f"This is the brief the {text} below was written from. Use it only to "
        "keep the rewrite true to what it asks for - its position and any "
        f"explicit asks. Do not add anything from it that the {text} does not "
        f"already say.\n\n<brief>\n{brief}\n</brief>"
    )
