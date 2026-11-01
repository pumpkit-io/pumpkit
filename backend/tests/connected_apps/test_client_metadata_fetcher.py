"""The real fetcher for Client ID Metadata Documents, against a faked network and resolver."""

import httpx
import pytest
import respx

from pumpkit.connected_apps.service.client_metadata import (
    ClientMetadataFetchError,
    HttpClientMetadataFetcher,
)
from pumpkit.core.config import settings

URL = "https://app.example.com/oauth/client.json"
DOCUMENT = {"client_id": URL, "redirect_uris": ["https://app.example.com/cb"]}


class resolving_to:
    """A resolver answering every host with these addresses, recording what it was asked."""

    def __init__(self, *addresses: str) -> None:
        self.addresses = list(addresses)
        self.asked: list[tuple[str, int]] = []

    async def __call__(self, host: str, port: int) -> list[str]:
        self.asked.append((host, port))
        return self.addresses


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "prod")


@pytest.fixture
def fetcher():
    return HttpClientMetadataFetcher(resolve=resolving_to("93.184.215.14"))


@respx.mock
async def test_a_json_document_is_returned_with_its_max_age(production, fetcher):
    route = respx.get(URL).mock(
        return_value=httpx.Response(
            200, json=DOCUMENT, headers={"Cache-Control": "public, max-age=300"}
        )
    )

    fetched = await fetcher.fetch(URL)

    assert fetched.document == DOCUMENT
    assert fetched.max_age_seconds == 300
    assert route.calls.last.request.headers["accept"] == "application/json"


@respx.mock
async def test_an_answer_without_max_age_has_none(production, fetcher):
    respx.get(URL).mock(
        return_value=httpx.Response(200, json=DOCUMENT, headers={"Cache-Control": "no-store"})
    )

    assert (await fetcher.fetch(URL)).max_age_seconds is None


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(404, json=DOCUMENT),
        httpx.Response(500),
        httpx.Response(302, headers={"Location": "https://app.example.com/other.json"}),
        httpx.Response(301, headers={"Location": "http://169.254.169.254/latest"}),
        httpx.Response(200, content=b"{" + b" " * 9000 + b"}"),
        httpx.Response(200, content=b"<html>not json</html>"),
    ],
    ids=["404", "500", "redirect", "redirect-to-metadata", "oversize", "html"],
)
@respx.mock
async def test_anything_but_a_small_json_200_is_refused(production, fetcher, answer):
    respx.get(URL).mock(return_value=answer)

    with pytest.raises(ClientMetadataFetchError):
        await fetcher.fetch(URL)
    assert len(respx.calls) == 1


@respx.mock
async def test_an_unreachable_host_is_refused(production, fetcher):
    respx.get(URL).mock(side_effect=httpx.ConnectTimeout("too slow"))

    with pytest.raises(ClientMetadataFetchError):
        await fetcher.fetch(URL)


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("10.0.0.5",),
        ("192.168.1.10",),
        ("169.254.169.254",),
        ("::1",),
        ("fd00::1",),
        ("93.184.215.14", "10.0.0.5"),
    ],
)
@respx.mock
async def test_a_host_resolving_to_a_non_global_address_is_refused_in_production(
    production, addresses
):
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=DOCUMENT))

    with pytest.raises(ClientMetadataFetchError):
        await HttpClientMetadataFetcher(resolve=resolving_to(*addresses)).fetch(URL)
    assert not route.called


@pytest.mark.parametrize(
    "url",
    [
        "https://93.184.215.14/oauth/client.json",
        "https://[2606:2800:220:1::]/oauth/client.json",
        "https://app.example.com:8443/oauth/client.json",
    ],
)
@respx.mock
async def test_ip_literal_hosts_and_other_ports_are_refused_in_production(production, fetcher, url):
    route = respx.get(url).mock(return_value=httpx.Response(200, json=DOCUMENT))

    with pytest.raises(ClientMetadataFetchError):
        await fetcher.fetch(url)
    assert not route.called


@respx.mock
async def test_an_unresolvable_host_is_refused(production):
    async def fail(host: str, port: int) -> list[str]:
        raise OSError("no such host")

    with pytest.raises(ClientMetadataFetchError):
        await HttpClientMetadataFetcher(resolve=fail).fetch(URL)


@respx.mock
async def test_a_local_instance_may_fetch_from_this_computer(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "local")
    url = "https://localhost:8443/oauth/client.json"
    respx.get(url).mock(return_value=httpx.Response(200, json=DOCUMENT))
    resolve = resolving_to("127.0.0.1")

    fetched = await HttpClientMetadataFetcher(resolve=resolve).fetch(url)

    assert fetched.document == DOCUMENT
    assert resolve.asked == [("localhost", 8443)]


@respx.mock
async def test_a_local_instance_still_refuses_private_addresses(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "local")
    respx.get(URL).mock(return_value=httpx.Response(200, json=DOCUMENT))

    with pytest.raises(ClientMetadataFetchError):
        await HttpClientMetadataFetcher(resolve=resolving_to("10.0.0.5")).fetch(URL)
