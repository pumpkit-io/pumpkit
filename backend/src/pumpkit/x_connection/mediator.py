from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.auth.schemas import UserProfileResponse
from pumpkit.auth.service.users import choose_photo
from pumpkit.core.logging import logger
from pumpkit.core.photos import PhotoFetcher
from pumpkit.x_connection import service
from pumpkit.x_connection.schemas import XAuthorizationStartResponse
from pumpkit.x_connection.x_publisher import XPublisher, XPublisherError, code_challenge_for


async def start_authorization(
    db: AsyncSession, publisher: XPublisher, user: User, now: datetime
) -> XAuthorizationStartResponse:
    """Store a pending authorization and return X's consent screen for it."""
    started = await service.start(db, user_id=user.id, now=now)
    url = publisher.build_authorize_url(
        state=started.state, code_challenge=code_challenge_for(started.code_verifier)
    )
    await db.commit()
    return XAuthorizationStartResponse(url=url)


async def disconnect(db: AsyncSession, publisher: XPublisher, user: User) -> None:
    """
    Delete the User's X connection, then ask X to revoke its grant. A failed revoke is only
    logged: the User asked to stop publishing, and Pumpkit no longer holds the tokens.
    """
    connection = await service.get_connection(db, user_id=user.id)
    if connection is None:
        raise service.XConnectionNotFoundError()
    refresh_token = service.refresh_token(connection)
    await service.delete_connection(db, connection)
    await db.commit()
    if not refresh_token:
        return
    try:
        await publisher.revoke(token=refresh_token, token_type_hint="refresh_token")
    except XPublisherError as error:
        logger.warning("Revoking a disconnected X connection's token failed: %s", error)


async def use_photo(
    db: AsyncSession, photo_fetcher: PhotoFetcher, user: User, now: datetime
) -> UserProfileResponse:
    """Copy the X account's photo into the User's Photo, as the User chose, answering the offer."""
    connection = await service.get_connection(db, user_id=user.id)
    if connection is None:
        raise service.XConnectionNotFoundError()
    if connection.photo_url is None:
        raise service.XPhotoNotFoundError()
    photo_data_url = await photo_fetcher.fetch(connection.photo_url)
    if photo_data_url is None:
        raise service.XPhotoUnavailableError()
    await choose_photo(db, user, photo_data_url, now)
    await service.answer_photo_offer(db, connection, now=now)
    await db.commit()
    return UserProfileResponse.model_validate(user)


async def decline_photo(db: AsyncSession, user: User, now: datetime) -> None:
    """The User said "Not now" to the X account's photo: stop offering it for this connection."""
    connection = await service.get_connection(db, user_id=user.id)
    if connection is None:
        raise service.XConnectionNotFoundError()
    await service.answer_photo_offer(db, connection, now=now)
    await db.commit()
