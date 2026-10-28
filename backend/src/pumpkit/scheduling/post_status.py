"""A Post's status, which its one Scheduled post decides (ADR 0015), and what each status allows."""

from typing import Literal, Optional

from pumpkit.core.errors import ConflictError
from pumpkit.scheduling.models import FAILED, PUBLISHED, ScheduledPostState

PostStatus = Literal["draft", "scheduled", "published", "failed"]
DRAFT: PostStatus = "draft"
SCHEDULED_STATUS: PostStatus = "scheduled"
PUBLISHED_STATUS: PostStatus = "published"
FAILED_STATUS: PostStatus = "failed"


def post_status(state: Optional[ScheduledPostState]) -> PostStatus:
    """
    From the state of the Post's Scheduled post, None when it has none. One being published is
    still Scheduled, and a Thread that failed partway is Failed.
    """
    if state is None:
        return DRAFT
    if state == PUBLISHED:
        return PUBLISHED_STATUS
    if state == FAILED:
        return FAILED_STATUS
    return SCHEDULED_STATUS


class TakesNoFeedback(ConflictError):
    pass


def check_takes_feedback(status: PostStatus) -> None:
    """Only a Draft or a Failed Post takes Feedback: the others' text is set to go, or gone."""
    if status == SCHEDULED_STATUS:
        raise TakesNoFeedback(
            "This Post is scheduled, so it takes no Feedback. Edit its text, or unschedule it first."
        )
    if status == PUBLISHED_STATUS:
        raise TakesNoFeedback(
            "This Post is published, so it takes no Feedback. Start a new Post to write another."
        )
