"""The Brief as the humanizer call is handed it, word for word from pumpkit-v6."""


def brief_message(brief: str) -> str:
    """The Brief, framed as what the rewrite must stay true to rather than more text to rewrite."""
    return (
        "This is the brief the post below was written from. Use it only to "
        "keep the rewrite true to what it asks for - its position and any "
        "explicit asks. Do not add anything from it that the post does not "
        f"already say.\n\n<brief>\n{brief}\n</brief>"
    )
