"""The Sign-up allowlist: which email addresses may sign in to this Instance."""

from pumpkit.core.config import settings
from pumpkit.core.errors import AppError

# The code the frontend shows a message for, as a 403 `detail` and as a sign-in `?error=`.
EMAIL_NOT_ALLOWED = "email_not_allowed"


class EmailNotAllowedError(AppError):
    status_code = 403
    public_detail = EMAIL_NOT_ALLOWED


def may_sign_in(email: str) -> bool:
    """
    True when the list is empty, or an entry matches: `@domain` matches the whole domain,
    any other entry one address, ignoring case.
    """
    entries = {entry.strip().lower() for entry in settings.SIGN_UP_ALLOWLIST.split(",")}
    entries.discard("")
    if not entries:
        return True
    address = email.strip().lower()
    domain = "@" + address.rpartition("@")[2]
    return address in entries or domain in entries
