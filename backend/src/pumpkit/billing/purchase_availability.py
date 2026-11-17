from pumpkit.core.config import settings
from pumpkit.core.errors import RefusalError


class PurchasesPausedError(RefusalError):
    status_code = 503

    def __init__(self) -> None:
        super().__init__(
            "New subscriptions are temporarily unavailable. Try again later.",
            code="BILLING_PURCHASES_PAUSED",
        )


def purchases_available() -> bool:
    return not settings.BILLING_PURCHASES_PAUSED


def require_purchases_available() -> None:
    if not purchases_available():
        raise PurchasesPausedError()
