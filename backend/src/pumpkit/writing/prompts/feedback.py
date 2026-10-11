"""Feedback as the revision call is handed it, word for word from pumpkit-v6."""


def feedback_message(feedback: str) -> str:
    """
    One function for both the new Feedback and the earlier ones rebuilt into the conversation,
    so the model never sees a framing it wasn't sent.
    """
    return (
        "Change the post you just wrote according to this feedback, and change "
        "nothing else. Keep every part the feedback does not ask about exactly "
        "as it is, and return the whole post rather than only the part that "
        f"changed.\n\nThe feedback:\n{feedback}"
    )
