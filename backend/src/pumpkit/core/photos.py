"""
The `PhotoFetcher` port, in `core` because auth and the X connection both use it. It never
raises: every failure is `None`, and callers carry on without a Photo.
"""

import asyncio
import base64
import io
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional, Protocol
from urllib.parse import urlsplit

import httpx
from PIL import Image

from pumpkit.core.logging import logger

# About 200 KB of base64: 256px square JPEGs are 30-60 KB, so PNG and webp uploads still fit.
MAX_PHOTO_DATA_URL_LENGTH = 220_000
PHOTO_DATA_URL_PATTERN = re.compile(r"data:image/(jpeg|png|webp);base64,[A-Za-z0-9+/=]+")

# The same square the web app crops an upload to.
PHOTO_SIZE = 256
_JPEG_QUALITY = 85
_TIMEOUT_SECONDS = 5.0
_DEADLINE_SECONDS = 15.0
_MAX_REDIRECTS = 3
_MAX_SOURCE_BYTES = 8 * 1024 * 1024
# Refuses decompression bombs long before Pillow's own limit of about 179 megapixels.
_MAX_SOURCE_PIXELS = 40_000_000


class PhotoFetcher(Protocol):
    async def fetch(self, url: str) -> Optional[str]:
        """The image at `url` as a Photo data URL, or `None` when there is no usable image."""
        ...


@dataclass(frozen=True)
class HttpPhotoFetcher:
    """Downloads over HTTPS, then crops to a centred square of at most `PHOTO_SIZE`, as JPEG."""

    deadline_seconds: float = _DEADLINE_SECONDS

    async def fetch(self, url: str) -> Optional[str]:
        try:
            async with asyncio.timeout(self.deadline_seconds):
                source = await _download(url)
            if source is None:
                return None
            return await asyncio.to_thread(_to_data_url, source)
        except Exception as error:
            logger.warning("Photo from %s failed: %s", _host(url), type(error).__name__)
            return None


async def _download(url: str) -> Optional[bytes]:
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            if not url.startswith("https://"):
                logger.warning("Photo address is not HTTPS: %s", _host(url))
                return None
            async with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = str(response.next_request.url) if response.next_request else ""
                    continue
                return await _read_image(response)
    logger.warning("Photo download redirected more than %s times", _MAX_REDIRECTS)
    return None


async def _read_image(response: httpx.Response) -> Optional[bytes]:
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


def _host(url: str) -> str:
    try:
        return urlsplit(url).hostname or "an address with no host"
    except ValueError:
        return "an unparseable address"


def _to_data_url(source: bytes) -> Optional[str]:
    with Image.open(io.BytesIO(source)) as image:
        width, height = image.size
        if width * height > _MAX_SOURCE_PIXELS:
            logger.warning("Photo has too many pixels: %sx%s", width, height)
            return None
        side = min(width, height)
        left, top = (width - side) // 2, (height - side) // 2
        square = _on_white(image).crop((left, top, left + side, top + side))
        if side > PHOTO_SIZE:
            square = square.resize((PHOTO_SIZE, PHOTO_SIZE), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        square.save(buffer, format="JPEG", quality=_JPEG_QUALITY)
    data_url = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    if len(data_url) > MAX_PHOTO_DATA_URL_LENGTH:
        return None
    return data_url


def _on_white(image: Image.Image) -> Image.Image:
    """JPEG has no transparency: without this, transparent areas of a PNG or webp turn black."""
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(background, rgba).convert("RGB")


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
