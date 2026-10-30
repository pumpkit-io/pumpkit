"""The rules a new or moved Scheduled post meets, each refusal in words for the User."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from pumpkit.core.errors import ConflictError, RefusedError
from pumpkit.posts.formats import part_name
from pumpkit.x_connection.x_length import x_weighted_length

# A publish time is at least this far ahead, so the User can't schedule one by mistake for now.
MIN_LEAD_TIME = timedelta(minutes=1)
MAX_LEAD_TIME = timedelta(days=365)


class RuleBroken(RefusedError):
    pass


class MonthFull(ConflictError):
    pass


class LivePartLocked(ConflictError):
    pass


def check_parts_written(parts: list[str]) -> None:
    """Every Part has some text: the User may have left one blank mid-edit."""
    for number, part in enumerate(parts, start=1):
        if not part:
            name = part_name(number, len(parts))
            raise RuleBroken(f"Write {name} first." if name else "Write the post first.")


def check_length(parts: list[str], *, limit: int) -> None:
    """Each Part by X's own count; the refusal names the first Part over the limit."""
    for number, text in enumerate(parts, start=1):
        length = x_weighted_length(text)
        if length > limit:
            subject = part_name(number, len(parts)) or "This post"
            raise RuleBroken(
                f"{subject} is {length:,} characters by X's count, over the {limit:,} limit."
            )


def check_live_parts_kept(live: list[str], parts: list[str]) -> None:
    """
    The texts of the live Parts open `parts` in their order, unchanged: they are on X, and the
    rest go out as replies to the last of them (ADR 0014). At least one Part follows them, or a
    reschedule would publish nothing.
    """
    for number, text in enumerate(live, start=1):
        if len(parts) < number or parts[number - 1] != text:
            raise LivePartLocked(f"Part {number} is already on X, so it can't change.")
    if live and len(parts) == len(live):
        raise LivePartLocked("Keep at least one part after the ones already on X.")


def check_text_keeps_live_parts(live_count: int, before: list[str], after: list[str]) -> None:
    """
    An edit of a Failed Thread's Text leaves the Text's Parts in the places of the live ones as
    they were: those places show what X has, and a retry skips them (ADR 0014).
    """
    for number in range(1, min(live_count, len(before), len(after)) + 1):
        if before[number - 1] != after[number - 1]:
            raise LivePartLocked(f"Part {number} is already on X, so it can't change.")


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


def check_month_has_room(count: int, *, adding: int, cap: int, moment: datetime) -> None:
    """
    `count` is the User's X posts already in the UTC month of `moment`, and `adding` the Parts
    that would join them.
    """
    if count + adding <= cap:
        return
    start, end = month_bounds(moment)
    resets = f"The cap resets on {end:%B} {end.day}, {end.year}."
    if count >= cap:
        raise MonthFull(
            f"You have {cap} X posts in {start:%B %Y}, the most for one month. {resets}"
        )
    raise MonthFull(
        f"These {adding} Parts would take you over the cap of {cap} X posts in {start:%B %Y}: "
        f"you have {count} already. {resets}"
    )


@dataclass(frozen=True)
class NewScheduledPost:
    """
    A Scheduled post as the web app or an MCP tool asks for it: the Post whose Text it copies,
    and `publish_at` or `publish_now`.
    """

    post_id: str
    publish_at: Optional[datetime] = None
    publish_now: bool = False
    # A Community URL or ID as pasted; None for the User's profile.
    community: Optional[str] = None
    # Ignored without a Community.
    share_with_followers: bool = False

    def __post_init__(self) -> None:
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

    # Every Part in order, the live ones first and unchanged.
    parts: Optional[list[str]] = None
    # Copy the Post's Text again in place of the Parts not live.
    copy_text: bool = False
    # A new time reschedules the Scheduled post on the X account connected now.
    publish_at: Optional[datetime] = None
    # Reschedules it for now and publishes it within the request.
    publish_now: bool = False
    destination: DestinationChange = field(default_factory=KeepDestination)
    # Ignored when the Scheduled post ends up on the profile.
    share_with_followers: Optional[bool] = None

    def __post_init__(self) -> None:
        if self.parts is not None and self.copy_text:
            raise RuleBroken("Give either the parts or the post's text, not both.")
        if self.publish_at is not None and self.publish_now:
            raise RuleBroken("Give either a publish time or publish now, not both.")
        if (
            self.parts is None
            and not self.copy_text
            and self.publish_at is None
            and not self.publish_now
            and isinstance(self.destination, KeepDestination)
            and self.share_with_followers is None
        ):
            raise RuleBroken(
                "Change the text, the publish time, the community or sharing with followers."
            )

    @property
    def reschedules(self) -> bool:
        return self.publish_at is not None or self.publish_now
