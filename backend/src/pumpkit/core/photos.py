"""
The `PhotoFetcher` port: copies a picture another service holds (Google, Gravatar, X) into a
data URL that fits a User's Photo. It lives in `core` because auth and the X connection both use it.

It never raises: a missing, oversized or undecodable image, or a failed request, is `None`, and
callers carry on without a Photo.

Mediators reach it only through `get_photo_fetcher`; tests override it with `FakePhotoFetcher`.
"""

import asyncio
import base64
import io
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional, Protocol

import httpx
from PIL import Image, UnidentifiedImageError

from pumpkit.core.logging import logger

# About 200 KB of base64: 256px square JPEGs are 30-60 KB, so PNG and webp uploads still fit.
MAX_PHOTO_DATA_URL_LENGTH = 220_000
PHOTO_DATA_URL_PATTERN = re.compile(r"data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+")

# The same square the web app crops an upload to.
PHOTO_SIZE = 256
_JPEG_QUALITY = 85
_TIMEOUT_SECONDS = 5.0
_MAX_SOURCE_BYTES = 8 * 1024 * 1024
# Refuses decompression bombs long before Pillow's own limit of about 179 megapixels.
_MAX_SOURCE_PIXELS = 40_000_000


class PhotoFetcher(Protocol):
    async def fetch(self, url: str) -> Optional[str]:
        """The image at `url` as a Photo data URL, or `None` when there is no usable image."""
        ...


class HttpPhotoFetcher:
    """Downloads over HTTPS, then crops to a centred square of at most `PHOTO_SIZE`, as JPEG."""

    async def fetch(self, url: str) -> Optional[str]:
        if not url.startswith("https://"):
            return None
        try:
            source = await _download(url)
        except httpx.HTTPError as error:
            logger.warning("Photo download failed: %s", type(error).__name__)
            return None
        if source is None:
            return None
        return await asyncio.to_thread(_to_data_url, source)


async def _download(url: str) -> Optional[bytes]:
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                logger.warning("Photo download returned %s", response.status_code)
                return None
            if not response.headers.get("Content-Type", "").startswith("image/"):
                logger.warning("Photo download returned something other than an image")
                return None
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > _MAX_SOURCE_BYTES:
                    logger.warning("Photo download exceeded %s bytes", _MAX_SOURCE_BYTES)
                    return None
            return bytes(body)


def _to_data_url(source: bytes) -> Optional[str]:
    try:
        with Image.open(io.BytesIO(source)) as image:
            width, height = image.size
            if width * height > _MAX_SOURCE_PIXELS:
                logger.warning("Photo has too many pixels: %sx%s", width, height)
                return None
            side = min(width, height)
            left, top = (width - side) // 2, (height - side) // 2
            square = image.convert("RGB").crop((left, top, left + side, top + side))
            if side > PHOTO_SIZE:
                square = square.resize((PHOTO_SIZE, PHOTO_SIZE), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            square.save(buffer, format="JPEG", quality=_JPEG_QUALITY)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        logger.warning("Photo could not be decoded: %s", type(error).__name__)
        return None
    data_url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    if len(data_url) > MAX_PHOTO_DATA_URL_LENGTH:
        return None
    return data_url


@dataclass
class FakePhotoFetcher:
    """
    Answers each URL with its data URL in `photos`, or `None` for any URL not there, as a failed
    download would. Every URL asked for is recorded in `fetched`.
    """

    photos: dict[str, str] = field(default_factory=dict)
    fetched: list[str] = field(default_factory=list)

    async def fetch(self, url: str) -> Optional[str]:
        self.fetched.append(url)
        return self.photos.get(url)


@lru_cache
def get_photo_fetcher() -> PhotoFetcher:
    """FastAPI dependency for the `PhotoFetcher` port."""
    return HttpPhotoFetcher()
