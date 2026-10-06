"""
The corpus as the user message both calls are handed, word for word from pumpkit-v6.

The `<creator>` tag is v6's markup, kept because the prompts were tuned on it.
"""

from app.writing.corpus import Corpus


def escape(text: str) -> str:
    """Escape `&` first, or the escapes would escape each other; nothing else is touched."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(corpus: Corpus) -> str:
    """One block per author, posts newest first."""
    blocks = []
    for group in corpus.groups:
        posts = "\n".join(f"<post>{escape(text)}</post>" for text in group.texts)
        blocks.append(f'<creator handle="{escape(group.handle)}">\n{posts}\n</creator>')
    return "\n\n".join(blocks)


def context_message(corpus: Corpus) -> str:
    return (
        "Below are real posts by the writers whose voice you are reproducing, "
        "grouped by author. They are examples of HOW to write, never of what to "
        "write about.\n\n" + render(corpus)
    )
