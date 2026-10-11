"""
The wall clock, behind a FastAPI dependency so tests can control time.

Time-dependent rules (Magic link cool-down and expiry) read the `Clock` once per request.
"""

from datetime import datetime, timezone
from typing import Callable

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    return datetime.now(timezone.utc)


def get_clock() -> Clock:
    return system_clock
