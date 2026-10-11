"""
The wall clock, behind a FastAPI dependency so tests can control time, and UTC normalisation.

Time-dependent rules (Magic link cool-down and expiry) read the `Clock` once per request.
"""

from datetime import datetime, timezone
from typing import Callable

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    return datetime.now(timezone.utc)


def get_clock() -> Clock:
    return system_clock


def as_utc(value: datetime) -> datetime:
    """
    Return a datetime loaded from the database as an aware UTC value.

    SQLite (tests) drops the offset Postgres keeps; values are stored in UTC, so naive is UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
