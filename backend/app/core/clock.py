"""
The wall clock, behind a FastAPI dependency so tests can control time.

Endpoints whose rules depend on the current time (Magic link cool-down and
expiry) take a `Clock` from `get_clock` and read it once per request.
"""

from datetime import datetime, timezone
from typing import Callable

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    """The current time, timezone-aware UTC."""
    return datetime.now(timezone.utc)


def get_clock() -> Clock:
    return system_clock
