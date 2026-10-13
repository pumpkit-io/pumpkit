"""
What the humanizer call is handed after Feedback, on top of what pumpkit-v6 sent it.

Written for Pumpkit, not ported: these messages carry the rules so `HUMANIZER_PROMPT` stays v6's.
"""

from typing import Sequence


def previous_final_message(final: str) -> str:
    return (
        "This is the post as I last saw it, before my latest feedback.\n\n"
        f"<previous_post>\n{final}\n</previous_post>"
    )


def feedback_given_message(feedback: Sequence[str]) -> str:
    """All of it, not only the latest, so an earlier ask survives a later Version."""
    return (
        "This is the feedback I gave on the post, oldest first. The last one is what the post "
        "below answers. Keep every explicit ask in all of them, even where your guidelines "
        "say otherwise, unless a later one overrides it. Where the feedback contradicts the "
        "brief, the feedback wins.\n\n"
        + "\n".join(f"<feedback>\n{text}\n</feedback>" for text in feedback)
    )


def revised_draft_message(draft: str) -> str:
    """
    Punctuation alone doesn't count as a change: the scrub runs on the Draft, not the Final, so
    a sentence the User left alone can differ from the previous Final in a quote or a dash.
    """
    return (
        "This is the post to rewrite, written from the previous post and my latest feedback. "
        "Return every sentence that is also in the previous post exactly as it is in <post> "
        "below, even if it moved. A sentence that differs only in punctuation counts as "
        "unchanged. Apply your guidelines only to the sentences that are new or reworded.\n\n"
        f"<post>\n{draft}\n</post>"
    )
