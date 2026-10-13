"""
What the humanizer call is handed after Feedback, on top of what pumpkit-v6 sent it.

Written for Pumpkit, not ported: these messages carry the rules so `HUMANIZER_PROMPT` stays v6's.
"""


def previous_final_message(final: str) -> str:
    return (
        "This is the post as I last saw it, before my latest feedback.\n\n"
        f"<previous_post>\n{final}\n</previous_post>"
    )


def latest_feedback_message(feedback: str) -> str:
    """
    Only the latest, framed as done: handed earlier Feedback as standing asks, the humanizer
    applied "write a much longer version" again on every later Version.
    """
    return (
        "This is my latest feedback on that post. The post below already applies it, so "
        "don't apply it again, and don't add, remove or reorder anything to serve it. If it "
        "asks for something your guidelines would undo, keep what it asks for.\n\n"
        f"<feedback>\n{feedback}\n</feedback>"
    )


def revised_draft_message(draft: str) -> str:
    """
    Punctuation alone doesn't count as a change: the scrub runs on the Draft, not the Final, so
    a sentence the User left alone can differ from the previous Final in a quote or a dash.
    """
    return (
        "This is the post to rewrite. Return every sentence that is also in the previous "
        "post exactly as it is in <post> below, even if it moved. A sentence that differs "
        "only in punctuation counts as unchanged. Apply your guidelines only to the "
        "sentences that are new or reworded, and don't add sentences or ideas the post "
        "doesn't have.\n\n"
        f"<post>\n{draft}\n</post>"
    )
