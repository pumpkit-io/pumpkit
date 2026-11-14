"""
Whether Pumpkit is writing a Version of a Post, and the timeout after which a write counts as lost
(ADR 0026).
"""

from datetime import datetime, timedelta
from typing import Literal, Optional

from pumpkit.core.time import as_utc
from pumpkit.posts.models import Post

# A write is three model steps of at most 240 seconds each once they hold a slot, plus waiting for
# one; real writes take about 40 seconds. Past this, the backend restarted or the task died.
WRITING_TIMEOUT = timedelta(minutes=15)
# Feedback still writes in its request with no superseded rule, so it holds the Text longer;
# #481 moves it to the background and to WRITING_TIMEOUT.
FEEDBACK_WRITING_TIMEOUT = timedelta(minutes=30)

# `writing` while a Version is being written; `not_written` for a Post whose first Version
# failed or was lost, which the User may retry.
WritingState = Literal["writing", "not_written"]
WRITING: WritingState = "writing"
NOT_WRITTEN: WritingState = "not_written"


def is_writing(post: Post, *, now: datetime) -> bool:
    """A Version is being written and its write isn't older than its timeout."""
    if post.writing_since is None:
        return False
    timeout = WRITING_TIMEOUT if post.text_version_number is None else FEEDBACK_WRITING_TIMEOUT
    return now - as_utc(post.writing_since) < timeout


def writing_state(post: Post, *, now: datetime) -> Optional[WritingState]:
    """None for a Post with a Text and no Version being written."""
    if is_writing(post, now=now):
        return WRITING
    if post.text_version_number is None:
        return NOT_WRITTEN
    return None
