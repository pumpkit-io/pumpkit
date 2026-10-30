"""
The HTTP photo fetcher against an image host mocked with respx, serving images made in each test.
"""

import asyncio
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
MOVED_PHOTO_URL = "https://lh4.googleusercontent.com/a/alice=s96-c"


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


def _image_response(content: bytes, content_type: str = "image/jpeg") -> httpx.Response:
    return httpx.Response(200, content=content, headers={"Content-Type": content_type})


def _redirect_to(location: str) -> httpx.Response:
    return httpx.Response(302, headers={"Location": location})


@respx.mock
async def test_a_redirect_to_another_https_address_is_followed():
    respx.get(PHOTO_URL).mock(return_value=_redirect_to(MOVED_PHOTO_URL))
    respx.get(MOVED_PHOTO_URL).mock(return_value=_image_response(_jpeg(96, 96)))

    assert await HttpPhotoFetcher().fetch(PHOTO_URL) is not None


@respx.mock
async def test_a_redirect_to_plain_http_is_nothing():
    plain_http = "http://lh4.googleusercontent.com/a/alice=s96-c"
    respx.get(PHOTO_URL).mock(return_value=_redirect_to(plain_http))
    followed = respx.get(plain_http).mock(return_value=_image_response(_jpeg(96, 96)))

    assert await HttpPhotoFetcher().fetch(PHOTO_URL) is None
    assert not followed.called


@respx.mock
async def test_a_chain_of_redirects_is_nothing():
    hops = [f"https://lh3.googleusercontent.com/hop/{i}" for i in range(10)]
    respx.get(PHOTO_URL).mock(return_value=_redirect_to(hops[0]))
    for here, there in zip(hops, hops[1:]):
        respx.get(here).mock(return_value=_redirect_to(there))
    respx.get(hops[-1]).mock(return_value=_image_response(_jpeg(96, 96)))

    assert await HttpPhotoFetcher().fetch(PHOTO_URL) is None


@respx.mock
async def test_a_download_that_runs_past_the_deadline_is_nothing():
    async def trickle():
        for _ in range(100):
            await asyncio.sleep(0.01)
            yield b"\xff"

    respx.get(PHOTO_URL).mock(
        return_value=httpx.Response(200, content=trickle(), headers={"Content-Type": "image/jpeg"})
    )

    assert await HttpPhotoFetcher(deadline_seconds=0.05).fetch(PHOTO_URL) is None


async def test_a_url_httpx_cannot_parse_is_nothing():
    assert await HttpPhotoFetcher().fetch("https://exa\x00mple.com/a.jpg") is None


@respx.mock
async def test_a_truncated_image_is_nothing():
    respx.get(PHOTO_URL).mock(return_value=_image_response(_jpeg(400, 400)[:600]))

    assert await HttpPhotoFetcher().fetch(PHOTO_URL) is None


@respx.mock
async def test_transparent_areas_turn_white():
    buffer = io.BytesIO()
    Image.new("RGBA", (96, 96), (0, 0, 0, 0)).save(buffer, format="PNG")
    respx.get(PHOTO_URL).mock(return_value=_image_response(buffer.getvalue(), "image/png"))

    data_url = await HttpPhotoFetcher().fetch(PHOTO_URL)

    assert data_url is not None
    assert min(_decoded(data_url).convert("L").tobytes()) >= 250
