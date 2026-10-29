"""A Post's status, which its one Scheduled post decides (ADR 0015), and what each status allows."""

from typing import Literal, Optional

from pumpkit.core.errors import ConflictError
from pumpkit.scheduling.models import FAILED, PUBLISHED, PUBLISHING, SCHEDULED, ScheduledPostState

PostStatus = Literal["draft", "scheduled", "published", "failed"]
DRAFT: PostStatus = "draft"
SCHEDULED_STATUS: PostStatus = "scheduled"
PUBLISHED_STATUS: PostStatus = "published"
FAILED_STATUS: PostStatus = "failed"


# One being published is still Scheduled, and a Thread that failed partway is Failed.
STATUS_OF_STATE: dict[ScheduledPostState, PostStatus] = {
    SCHEDULED: SCHEDULED_STATUS,
    PUBLISHING: SCHEDULED_STATUS,
    PUBLISHED: PUBLISHED_STATUS,
    FAILED: FAILED_STATUS,
}


def post_status(state: Optional[ScheduledPostState]) -> PostStatus:
    """From the state of the Post's Scheduled post, None when it has none."""
    return DRAFT if state is None else STATUS_OF_STATE[state]


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


class TextIsSet(ConflictError):
    pass


def check_text_changes(status: PostStatus) -> None:
    """Only a Draft or a Failed Post's Text changes: the others' text is set to go, or gone."""
    if status == SCHEDULED_STATUS:
        raise TextIsSet(
            "This Post is scheduled, so its Text is set. Edit its Scheduled post, or unschedule it"
            " first."
        )
    if status == PUBLISHED_STATUS:
        raise TextIsSet(
            "This Post is published, so its Text is set. Start a new Post to write another."
        )
