from typing import Literal, Optional

from pydantic import BaseModel

NextStep = Literal["paywall", "x_connection", "persona"]


class OnboardingResponse(BaseModel):
    """Where the web app sends the signed-in User next; null once Pumpkit is open to them."""

    next_step: Optional[NextStep]
