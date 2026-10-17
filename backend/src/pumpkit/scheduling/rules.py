"""The rules a new or moved Scheduled post meets, each refusal in words for the User."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from pumpkit.core.errors import ConflictError, RefusedError
from pumpkit.x_connection.x_length import x_weighted_length

# A publish time is at least this far ahead, so the User can't schedule one by mistake for now.
MIN_LEAD_TIME = timedelta(minutes=1)
MAX_LEAD_TIME = timedelta(days=365)


class RuleBroken(RefusedError):
    pass


class MonthFull(ConflictError):
    pass


def check_length(text: str, *, limit: int) -> None:
    """By X's own count."""
    length = x_weighted_length(text)
    if length > limit:
        raise RuleBroken(
            f"This post is {length:,} characters by X's count, over the {limit:,} limit."
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


@dataclass(frozen=True)
class NewScheduledPost:
    """
    A Scheduled post as the web app or an MCP tool asks for it: typed `text` or the Version
    whose Final it copies, and `publish_at` or `publish_now`.
    """

    text: Optional[str] = None
    version_id: Optional[str] = None
    publish_at: Optional[datetime] = None
    publish_now: bool = False
    # A Community URL or ID as pasted; None for the User's profile.
    community: Optional[str] = None
    # Ignored without a Community.
    share_with_followers: bool = False

    def __post_init__(self) -> None:
        if (self.text is None) == (self.version_id is None):
            raise RuleBroken("Give either the text or a Version id, not both.")
        if (self.publish_at is None) == (not self.publish_now):
            raise RuleBroken("Give either a publish time or publish now, not both.")


@dataclass(frozen=True)
class KeepDestination:
    pass


@dataclass(frozen=True)
class ToProfile:
    pass


@dataclass(frozen=True)
class ToCommunity:
    # A Community URL or ID as pasted.
    pasted: str


DestinationChange = Union[KeepDestination, ToProfile, ToCommunity]


@dataclass(frozen=True)
class ScheduledPostEdit:
    """What an edit changes about a Scheduled post; None and `KeepDestination` leave it as is."""

    text: Optional[str] = None
    # A new time reschedules the Scheduled post on the X account connected now.
    publish_at: Optional[datetime] = None
    destination: DestinationChange = field(default_factory=KeepDestination)
    # Ignored when the Scheduled post ends up on the profile.
    share_with_followers: Optional[bool] = None

    def __post_init__(self) -> None:
        if (
            self.text is None
            and self.publish_at is None
            and isinstance(self.destination, KeepDestination)
            and self.share_with_followers is None
        ):
            raise RuleBroken(
                "Change the text, the publish time, the Community or sharing with followers."
            )
