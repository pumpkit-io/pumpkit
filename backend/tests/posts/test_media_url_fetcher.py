"""
`HttpMediaUrlFetcher`, which downloads the file an AI app names by URL: public hosts only, each
redirect checked again, capped by the file's kind while it downloads, and within a deadline.
"""

import asyncio

import httpx
import pytest
import respx

from pumpkit.core.config import settings
from pumpkit.posts.media_fetcher import HttpMediaUrlFetcher
from pumpkit.posts.media_files import MediaRefused
from tests.media_files import MB, padded, png

URL = "https://images.example.com/chart.png"


def resolving(answers: dict[str, str]):
    async def resolve(host: str, port: int) -> list[str]:
        return [answers[host]]

    return resolve


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "prod")


@pytest.fixture
def fetcher():
    return HttpMediaUrlFetcher(resolve=resolving({"images.example.com": "93.184.215.14"}))


async def _refusal(fetcher: HttpMediaUrlFetcher, url: str) -> MediaRefused:
    with pytest.raises(MediaRefused) as refused:
        async with fetcher.fetch(url):
            pass
    return refused.value


@respx.mock
async def test_the_file_is_handed_over_whole_with_its_size(production, fetcher):
    image = png(40, 30)
    respx.get(URL).mock(return_value=httpx.Response(200, content=image))

    async with fetcher.fetch(URL) as received:
        assert received.file.read() == image
        assert received.byte_size == len(image)


@respx.mock
async def test_a_redirect_is_followed_to_a_public_host(production):
    image = png()
    respx.get(URL).mock(
        return_value=httpx.Response(302, headers={"location": "https://cdn.example.net/a.png"})
    )
    respx.get("https://cdn.example.net/a.png").mock(return_value=httpx.Response(200, content=image))
    fetcher = HttpMediaUrlFetcher(
        resolve=resolving(
            {"images.example.com": "93.184.215.14", "cdn.example.net": "93.184.215.15"}
        )
    )

    async with fetcher.fetch(URL) as received:
        assert received.file.read() == image


@respx.mock
async def test_a_redirect_to_a_private_address_is_refused(production):
    respx.get(URL).mock(
        return_value=httpx.Response(302, headers={"location": "https://internal.example.net/a"})
    )
    inside = respx.get("https://internal.example.net/a").mock(return_value=httpx.Response(200))
    fetcher = HttpMediaUrlFetcher(
        resolve=resolving(
            {"images.example.com": "93.184.215.14", "internal.example.net": "10.0.0.5"}
        )
    )

    refusal = await _refusal(fetcher, URL)

    assert refusal.code == "MEDIA_URL_UNREACHABLE"
    assert not inside.called


@respx.mock
async def test_endless_redirects_are_refused(production, fetcher):
    respx.get(URL).mock(return_value=httpx.Response(302, headers={"location": URL}))

    assert (await _refusal(fetcher, URL)).code == "MEDIA_URL_UNREACHABLE"


@pytest.mark.parametrize(
    "url",
    [
        "http://images.example.com/chart.png",
        "https://93.184.215.14/chart.png",
        "https://images.example.com:8443/chart.png",
        "https://images.example.com:99999/chart.png",
        "file:///etc/passwd",
    ],
)
@respx.mock
async def test_anything_but_https_on_a_named_host_is_refused_in_production(
    production, fetcher, url
):
    route = respx.route().mock(return_value=httpx.Response(200, content=png()))

    assert (await _refusal(fetcher, url)).code == "MEDIA_URL_UNREACHABLE"
    assert not route.called


@respx.mock
async def test_a_host_resolving_to_a_private_address_is_refused(production):
    route = respx.get(URL).mock(return_value=httpx.Response(200, content=png()))
    fetcher = HttpMediaUrlFetcher(resolve=resolving({"images.example.com": "192.168.1.2"}))

    assert (await _refusal(fetcher, URL)).code == "MEDIA_URL_UNREACHABLE"
    assert not route.called


@respx.mock
async def test_an_answer_other_than_200_is_refused(production, fetcher):
    respx.get(URL).mock(return_value=httpx.Response(404))

    refusal = await _refusal(fetcher, URL)

    assert refusal.detail == (
        "Pumpkit couldn't download the file at this URL (answered HTTP 404). Give a public https"
        " URL of the file itself."
    )


@respx.mock
async def test_a_file_past_its_kinds_limit_is_refused_while_it_downloads(production, fetcher):
    sent = 0

    async def body():
        nonlocal sent
        data = padded(png(), 8 * MB)
        for start in range(0, len(data), 64 * 1024):
            sent += 64 * 1024
            yield data[start : start + 64 * 1024]

    respx.get(URL).mock(return_value=httpx.Response(200, content=body()))

    refusal = await _refusal(fetcher, URL)

    assert refusal.code == "MEDIA_TOO_LARGE"
    assert sent < 6 * MB


@respx.mock
async def test_a_file_of_a_type_pumpkit_doesnt_take_is_refused(production, fetcher):
    respx.get(URL).mock(return_value=httpx.Response(200, content=b"<html>not an image</html>"))

    assert (await _refusal(fetcher, URL)).code == "MEDIA_TYPE_UNSUPPORTED"


@respx.mock
async def test_a_file_trickled_slowly_is_refused_at_the_deadline(production):
    async def trickle():
        yield png()[:16]
        for _ in range(100):
            await asyncio.sleep(0.01)
            yield b"\0"

    respx.get(URL).mock(return_value=httpx.Response(200, content=trickle()))
    fetcher = HttpMediaUrlFetcher(
        resolve=resolving({"images.example.com": "93.184.215.14"}), deadline_seconds=0.1
    )

    refusal = await asyncio.wait_for(_refusal(fetcher, URL), timeout=0.5)

    assert refusal.code == "MEDIA_URL_UNREACHABLE"
