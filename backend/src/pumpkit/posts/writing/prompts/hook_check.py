"""
The question Jev answers before a Feedback Version's hook step: does the opening need a new Hook?
Written for Pumpkit, not ported.

Jev reads a `state` with the conversation (the Brief, each Final and the Feedback after it) and
the latest draft, the revision just written from the last Feedback.
"""

from pumpkit.core.classifier import ChoiceQuestion

NEW_HOOK = "new_hook"
KEEP_HOOK = "keep_hook"
USER_WROTE_HOOK = "user_wrote_hook"

# The answer's key in Jev's response.
HOOK_CHECK_QUESTION_NAME = "opening"

HOOK_CHECK_QUESTION = ChoiceQuestion(
    instructions=(
        "A user is writing one post for X with an assistant. In `conversation`, the user's first "
        "turn is the brief the post is written from; every later user turn is feedback on the "
        "assistant's previous version of the post, and every `pumpkit` turn is a version the user "
        "saw. `latest_draft` is the new version, rewritten from the user's last feedback. "
        "Decide whether the opening of `latest_draft`, its first line or lines, should now be "
        "replaced with a new hook. Judge by what the last feedback asks for and by whether the "
        "opening still fits the rest of `latest_draft`. When the last feedback dictates the "
        "opening, quotes words for it, or asks to change it in any way, answer user_wrote_hook, "
        "even if it also asks for other changes: the user's own opening must never be replaced."
    ),
    criteria={
        NEW_HOOK: (
            "The last feedback asks to rewrite the whole post or changes what the post is about, "
            "or the opening of latest_draft no longer fits the text after it, and the feedback "
            "says nothing about the opening itself."
        ),
        KEEP_HOOK: (
            "The last feedback changes only text after the opening, such as a line in the body, "
            "the ending, the length or the tone, and the opening still fits the post."
        ),
        USER_WROTE_HOOK: (
            "The last feedback dictates the opening, gives words for it, or asks to edit it, for "
            'example "start with: I shipped 40 things", "make the first line punchier" or '
            '"keep the number in the opening".'
        ),
    },
)
