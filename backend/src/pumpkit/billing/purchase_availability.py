from pumpkit.auth.models import User
from pumpkit.core.config import settings
from pumpkit.core.errors import RefusalError


class PurchasesPausedError(RefusalError):
    status_code = 503

    def __init__(self) -> None:
        super().__init__(
            "Purchases are temporarily unavailable. Try again later.",
            code="BILLING_PURCHASES_PAUSED",
        )


def purchases_available(user: User) -> bool:
    return not settings.BILLING_PURCHASES_PAUSED or (
        user.id == settings.BILLING_VERIFICATION_USER_ID and user.x_user_id is not None
    )


def require_purchases_available(user: User) -> None:
    if not purchases_available(user):
        raise PurchasesPausedError()
