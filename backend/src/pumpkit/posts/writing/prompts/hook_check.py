"""
The question Jev answers before a Feedback Version's hook call: does the next Version need a new
Hook? Written for Pumpkit, not ported.

Jev reads a `state` with the conversation (the Brief, each Final and the Feedback after it),
before anything is written from the last Feedback.
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
        "saw. The assistant will now rewrite the post from the user's last feedback. Decide "
        "whether the rewritten post should open with a new hook in place of the opening of the "
        "last `pumpkit` turn, its first line or lines. Judge by what the last feedback asks for. "
        "When the last feedback dictates the opening, quotes words for it, or asks to change it "
        "in any way, answer user_wrote_hook, even if it also asks for other changes: the user's "
        "own opening must never be replaced."
    ),
    criteria={
        NEW_HOOK: (
            "The last feedback asks to rewrite the whole post or changes what the post is about, "
            "so the current opening won't fit the rewritten post, and the feedback says nothing "
            "about the opening itself."
        ),
        KEEP_HOOK: (
            "The last feedback changes only text after the opening, such as a line in the body, "
            "the ending, the length or the tone, so the opening will still fit the post."
        ),
        USER_WROTE_HOOK: (
            "The last feedback dictates the opening, gives words for it, or asks to edit it, for "
            'example "start with: I shipped 40 things", "make the first line punchier" or '
            '"keep the number in the opening".'
        ),
    },
)
