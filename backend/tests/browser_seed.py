"""Deterministic identities for CLI-only browser fixtures in a managed local stack."""

import hashlib

from pumpkit.auth.models import User
from pumpkit.core.config import settings

_IDENTITIES = {
    "e2e@e2e-user.dev": ("2001", "e2e_user"),
    "e2e-onboarding@e2e-user.dev": ("2002", "e2e_newcomer"),
    "e2e-usage@e2e-user.dev": ("2003", "e2e_usage"),
}


def x_id_for(email: str) -> str:
    if settings.ENV != "local" or not settings.X_API_URL:
        raise RuntimeError("Browser seeds require the managed local X stand-in.")
    fixed = _IDENTITIES.get(email)
    return fixed[0] if fixed else str(int.from_bytes(hashlib.sha256(email.encode()).digest()[:8]))


def bind_x_identity(user: User) -> None:
    user.x_user_id = x_id_for(user.email)
    user.x_handle = _IDENTITIES.get(user.email, ("", "e2e_fixture"))[1]
