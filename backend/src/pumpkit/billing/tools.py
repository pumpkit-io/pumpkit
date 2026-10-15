"""The billing MCP tool: subscribing and managing a Subscription happen in the web app."""

from pumpkit.auth.models import User
from pumpkit.billing import service
from pumpkit.core.config import settings
from pumpkit.core.mcp_tools import READ_ONLY, READ_ONLY_RATE, McpTool, ToolCall
from pumpkit.core.schemas import LinkToolResponse


async def manage_subscription(call: ToolCall[User]) -> LinkToolResponse:
    """
    Where the User subscribes to a Plan, changes or cancels their Subscription, or updates
    their payment details: the billing page of the Pumpkit web app, since paying needs a browser.
    """
    if not service.sells_plans():
        return LinkToolResponse(
            message="This Instance sells no Plans: you can use all of Pumpkit without a "
            "Subscription.",
            url=None,
        )
    url = f"{settings.frontend_url()}/billing"
    return LinkToolResponse(
        message=f"Subscribe or manage your Subscription on the billing page: {url}", url=url
    )


TOOLS = [
    McpTool(manage_subscription, rate=READ_ONLY_RATE, annotations=READ_ONLY, needs_access=False),
]
