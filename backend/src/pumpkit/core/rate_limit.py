import math
from datetime import datetime, timezone

from limits import parse
from slowapi import Limiter
from slowapi.util import get_remote_address

from pumpkit.core.errors import RetryLaterError

limiter = Limiter(key_func=get_remote_address)


def hit_user_limit(name: str, user_id: str, rate: str) -> None:
    """
    Count one call of `name` by the User against `rate` (slowapi's notation, such as
    "20/minute"), or raise `RetryLaterError` once the User is over it. Shares the
    route limiter's storage, so `limiter.reset()` clears these counts too.
    """
    item = parse(rate)
    if limiter.limiter.hit(item, "user", name, user_id):
        return
    reset_time = limiter.limiter.get_window_stats(item, "user", name, user_id).reset_time
    # The limiter counts in wall-clock time, not the app's Clock.
    now = datetime.now(timezone.utc)
    retry_at = datetime.fromtimestamp(reset_time, timezone.utc)
    seconds = max(1, math.ceil((retry_at - now).total_seconds()))
    raise RetryLaterError(
        f"You've called {name} too often. Try again in {seconds} seconds.",
        retry_at=retry_at,
        now=now,
    )
