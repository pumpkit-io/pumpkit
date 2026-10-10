from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.scheduled_posts as scheduled_posts_service
import app.api.services.x_authorizations as x_authorizations_service
import app.api.services.x_connections as x_connections_service
from app.core.logger import logger
from app.core.x_publisher import (
    XPublisher,
    XPublisherError,
    XReconnectNeededError,
    code_challenge_for,
)
from app.db.models import User, XConnection
from app.publishing.x_length import X_POST_MAX_CHARS
from app.schemas.x_connection import XAuthorizationStartResponse, XConnectionResponse


async def _response(db: AsyncSession, connection: XConnection) -> XConnectionResponse:
    return XConnectionResponse(
        handle=connection.handle,
        char_limit=X_POST_MAX_CHARS,
        needs_reconnect=connection.needs_reconnect,
        scheduled_posts_waiting=await scheduled_posts_service.count_waiting(
            db, user_id=connection.user_id, x_user_id=connection.x_user_id
        ),
    )


def _owned_elsewhere(handle: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"@{handle} is already connected to another Pumpkit account.",
    )


async def _connection_or_404(db: AsyncSession, *, user_id: str) -> XConnection:
    connection = await x_connections_service.get_connection(db, user_id=user_id)
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="You haven't connected an X account."
        )
    return connection


async def get_connection(db: AsyncSession, user: User) -> XConnectionResponse:
    return await _response(db, await _connection_or_404(db, user_id=user.id))


async def start_authorization(
    db: AsyncSession, publisher: XPublisher, user: User, now: datetime
) -> XAuthorizationStartResponse:
    """Store a pending authorization and return X's consent screen for it."""
    started = await x_authorizations_service.start(db, user_id=user.id, now=now)
    url = publisher.build_authorize_url(
        state=started.state, code_challenge=code_challenge_for(started.code_verifier)
    )
    await db.commit()
    return XAuthorizationStartResponse(url=url)


async def complete_authorization(
    db: AsyncSession, publisher: XPublisher, user: User, code: str, state: str, now: datetime
) -> XConnectionResponse:
    """
    Trade X's code for tokens and make the account the User's X connection, replacing the
    one they had. Refused when the state isn't a live one of theirs, or the account is
    another User's.
    """
    user_id = user.id
    code_verifier = await x_authorizations_service.consume(
        db, user_id=user_id, state=state, now=now
    )
    # Commit the delete before calling X: the state is then spent even if X fails, and no
    # transaction stays open across X's calls.
    await db.commit()
    if code_verifier is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This X authorization expired or was already used. Connect X again.",
        )

    try:
        tokens = await publisher.exchange_code(code=code, code_verifier=code_verifier, now=now)
        account = await publisher.fetch_account(access_token=tokens.access_token)
    except XReconnectNeededError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X didn't give Pumpkit access to your account. Connect X again.",
        )

    # The grant isn't revoked here: X may scope revocation to the account, cutting off its owner.
    owner = await x_connections_service.get_connection_by_x_user_id(db, x_user_id=account.user_id)
    if owner is not None and owner.user_id != user_id:
        raise _owned_elsewhere(account.handle)
    try:
        connection = await x_connections_service.save_connection(
            db, user_id=user_id, account=account, tokens=tokens, now=now
        )
        await db.commit()
    except IntegrityError:
        # Another User connected the same X account between the check and the save.
        raise _owned_elsewhere(account.handle)
    return await _response(db, connection)


async def disconnect(db: AsyncSession, publisher: XPublisher, user: User) -> None:
    """
    Delete the User's X connection, then ask X to revoke its grant. A failed revoke is only
    logged: the User asked to stop publishing, and Pumpkit no longer holds the tokens.
    """
    connection = await _connection_or_404(db, user_id=user.id)
    refresh_token = x_connections_service.refresh_token(connection)
    await x_connections_service.delete_connection(db, connection)
    await db.commit()
    if not refresh_token:
        return
    try:
        await publisher.revoke(token=refresh_token, token_type_hint="refresh_token")
    except XPublisherError as error:
        logger.warning("Revoking a disconnected X connection's token failed: %s", error)
