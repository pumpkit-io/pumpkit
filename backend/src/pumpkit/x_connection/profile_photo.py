from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from pumpkit.auth.models import User
from pumpkit.auth.service.users import save_x_photo
from pumpkit.core.photos import PhotoFetcher


async def sync_photo(
    db: AsyncSession, user: User, *, photo_url: Optional[str], photo_fetcher: PhotoFetcher
) -> None:
    if user.x_user_id is None:
        return
    if photo_url is None:
        await save_x_photo(db, user, None)
    else:
        photo = await photo_fetcher.fetch(photo_url)
        if photo is not None:
            await save_x_photo(db, user, photo)
