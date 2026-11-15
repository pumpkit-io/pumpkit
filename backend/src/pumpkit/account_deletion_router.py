from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pumpkit import account_deletion
from pumpkit.auth.dependencies import get_current_user
from pumpkit.auth.models import User
from pumpkit.auth.service import sessions as auth_sessions
from pumpkit.billing.gateway import BillingGateway, get_billing_gateway
from pumpkit.core.background import TaskRegistry, get_background_tasks
from pumpkit.core.db.session import get_async_db, get_session_maker
from pumpkit.core.rate_limit import limiter
from pumpkit.core.storage import FileStorage, get_file_storage
from pumpkit.x_connection.x_publisher import XPublisher, get_x_publisher

# Deletion reaches across every area, which `auth` can't import, so it sits at the package root.
router = APIRouter(tags=["users"])


class AccountDeletionRequest(BaseModel):
    """The User's handle, typed to confirm, with or without "@"."""

    handle: str = Field(max_length=64)


@router.delete("/users/me", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def delete_current_user(
    request: Request,
    confirmation: AccountDeletionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
    gateway: BillingGateway = Depends(get_billing_gateway),
    publisher: XPublisher = Depends(get_x_publisher),
    tasks: TaskRegistry = Depends(get_background_tasks),
    sessions: async_sessionmaker[AsyncSession] = Depends(get_session_maker),
    storage: FileStorage = Depends(get_file_storage),
) -> Response:
    await account_deletion.delete_own_account(
        db,
        gateway,
        publisher,
        tasks,
        sessions,
        storage,
        user=current_user,
        handle=confirmation.handle,
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    auth_sessions.clear_refresh_cookie(response)
    return response
