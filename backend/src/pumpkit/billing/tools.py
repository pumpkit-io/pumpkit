"""The billing MCP tool: subscribing and managing a Subscription happen in the web app."""

from pumpkit.auth.models import User
from pumpkit.billing import mediator
from pumpkit.core.mcp_tools import READ_ONLY, READ_ONLY_RATE, McpTool, ToolCall
from pumpkit.core.schemas import LinkToolResponse


async def manage_subscription(call: ToolCall[User]) -> LinkToolResponse:
    """
    Where the User subscribes to a Plan, changes or cancels their Subscription, or updates
    their payment details: the Settings page of the Pumpkit web app, since paying needs a browser.
    """
    return mediator.subscription_link()


TOOLS = [
    McpTool(manage_subscription, rate=READ_ONLY_RATE, annotations=READ_ONLY, needs_access=False),
]
