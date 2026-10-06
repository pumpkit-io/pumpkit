import math
from datetime import datetime


class RetryLaterError(Exception):
    """
    A request refused until `retry_at`. Answered as a 429 whose body carries `detail` and
    `retry_at`, with a `Retry-After` header in whole seconds.
    """

    def __init__(self, detail: str, *, retry_at: datetime, now: datetime) -> None:
        super().__init__(detail)
        self.detail = detail
        self.retry_at = retry_at
        # Rounded up, so a client that waits exactly this long is not refused again.
        self.retry_after_seconds = max(1, math.ceil((retry_at - now).total_seconds()))
