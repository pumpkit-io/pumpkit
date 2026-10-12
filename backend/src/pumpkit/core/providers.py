from typing import Callable

from fastapi import HTTPException, status


def require_provider(is_configured: Callable[[], bool]) -> Callable[[], None]:
    """
    A FastAPI dependency that answers 404 while `is_configured()` is false: an Instance
    without a provider has no routes for it (ADR 0011).
    """

    def dependency() -> None:
        if not is_configured():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    return dependency
