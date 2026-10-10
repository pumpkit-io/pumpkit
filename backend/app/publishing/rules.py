"""The rules a new or moved Scheduled post meets, each refusal in words for the User."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.publishing.x_length import X_POST_MAX_CHARS, x_weighted_length

# A publish time is at least this far ahead, so the User can't schedule one by mistake for now.
MIN_LEAD_TIME = timedelta(minutes=1)
MAX_LEAD_TIME = timedelta(days=365)


class RuleBroken(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class MonthFull(RuleBroken):
    pass


def check_length(text: str) -> None:
    """By X's own count."""
    length = x_weighted_length(text)
    if length > X_POST_MAX_CHARS:
        raise RuleBroken(
            f"This post is {length} characters by X's count, over the {X_POST_MAX_CHARS} limit."
        )


def check_publish_at(publish_at: Optional[datetime], *, now: datetime) -> datetime:
    """The publish time in UTC: a whole minute, one minute to a year from `now`."""
    if publish_at is None:
        raise RuleBroken("Pick a date and time.")
    publish_at = publish_at.astimezone(timezone.utc)
    if publish_at.second or publish_at.microsecond:
        raise RuleBroken("Pick a time on a whole minute.")
    if publish_at - now < MIN_LEAD_TIME:
        raise RuleBroken("Pick a time at least a minute from now.")
    if publish_at - now > MAX_LEAD_TIME:
        raise RuleBroken("Pick a time within a year from now.")
    return publish_at


def month_bounds(moment: datetime) -> tuple[datetime, datetime]:
    """The start of the UTC calendar month holding `moment`, and the start of the next one."""
    start = moment.astimezone(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    if start.month == 12:
        return start, start.replace(year=start.year + 1, month=1)
    return start, start.replace(month=start.month + 1)


def check_month_has_room(count: int, *, cap: int, moment: datetime) -> None:
    """`count` is the User's Scheduled posts already in the UTC month of `moment`."""
    if count < cap:
        return
    start, end = month_bounds(moment)
    raise MonthFull(
        f"You have {cap} Scheduled posts in {start:%B %Y}, the most for one month. "
        f"The cap resets on {end:%B} {end.day}, {end.year}."
    )
