"""
The HTTP photo fetcher against recorded responses from an image host, through respx.
"""

import base64
import io

import httpx
import pytest
import respx
from PIL import Image

from pumpkit.core.photos import (
    MAX_PHOTO_DATA_URL_LENGTH,
    PHOTO_DATA_URL_PATTERN,
    HttpPhotoFetcher,
)

PHOTO_URL = "https://lh3.googleusercontent.com/a/alice=s96-c"


def _jpeg(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 80, 40)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _decoded(data_url: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1])))


@respx.mock
async def test_an_image_comes_back_as_a_square_photo_data_url_within_the_upload_limits():
    respx.get(PHOTO_URL).mock(
        return_value=httpx.Response(
            200, content=_jpeg(1200, 800), headers={"Content-Type": "image/jpeg"}
        )
    )

    data_url = await HttpPhotoFetcher().fetch(PHOTO_URL)

    assert data_url is not None
    assert PHOTO_DATA_URL_PATTERN.fullmatch(data_url)
    assert len(data_url) <= MAX_PHOTO_DATA_URL_LENGTH
    assert _decoded(data_url).size == (256, 256)


@respx.mock
async def test_a_small_png_is_kept_at_its_own_size():
    buffer = io.BytesIO()
    Image.new("RGBA", (96, 96), (0, 0, 255, 128)).save(buffer, format="PNG")
    respx.get(PHOTO_URL).mock(
        return_value=httpx.Response(
            200, content=buffer.getvalue(), headers={"Content-Type": "image/png"}
        )
    )

    data_url = await HttpPhotoFetcher().fetch(PHOTO_URL)

    assert data_url is not None
    assert PHOTO_DATA_URL_PATTERN.fullmatch(data_url)
    assert _decoded(data_url).size == (96, 96)


@respx.mock
async def test_a_missing_image_is_nothing():
    respx.get(PHOTO_URL).mock(return_value=httpx.Response(404, text="Not Found"))

    assert await HttpPhotoFetcher().fetch(PHOTO_URL) is None


@respx.mock
async def test_a_page_that_is_not_an_image_is_nothing():
    respx.get(PHOTO_URL).mock(
        return_value=httpx.Response(
            200, text="<html>Sign in</html>", headers={"Content-Type": "text/html"}
        )
    )

    assert await HttpPhotoFetcher().fetch(PHOTO_URL) is None


@respx.mock
async def test_bytes_labelled_as_an_image_that_do_not_decode_are_nothing():
    respx.get(PHOTO_URL).mock(
        return_value=httpx.Response(
            200, content=b"not really a jpeg", headers={"Content-Type": "image/jpeg"}
        )
    )

    assert await HttpPhotoFetcher().fetch(PHOTO_URL) is None


@respx.mock
async def test_an_oversized_body_is_nothing():
    respx.get(PHOTO_URL).mock(
        return_value=httpx.Response(
            200, content=b"\xff" * (9 * 1024 * 1024), headers={"Content-Type": "image/jpeg"}
        )
    )

    assert await HttpPhotoFetcher().fetch(PHOTO_URL) is None


@respx.mock
async def test_a_timeout_is_nothing():
    respx.get(PHOTO_URL).mock(side_effect=httpx.ReadTimeout("timed out"))

    assert await HttpPhotoFetcher().fetch(PHOTO_URL) is None


@pytest.mark.parametrize("url", ["", "file:///etc/passwd", "ftp://example.com/a.jpg"])
async def test_a_url_that_is_not_https_is_nothing(url):
    assert await HttpPhotoFetcher().fetch(url) is None
