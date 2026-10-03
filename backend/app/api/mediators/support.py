from fastapi import status
from fastapi.responses import RedirectResponse

from app.core.config import settings


def build_contact_redirect_response() -> RedirectResponse:
    """
    303-redirect to a mailto: link for the support address. Browsers follow
    Location: mailto:... transparently, so the anchor on the frontend does
    not need to know the support address.
    """
    target = f"mailto:{settings.RESEND_SUPPORT_ADDRESS}"
    return RedirectResponse(url=target, status_code=status.HTTP_303_SEE_OTHER)
