import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

from app.core.config import settings
from app.core.x_reader import (
    TWITTERAPI_IO_LAST_TWEETS_URL,
    FetchedPost,
    HandleNotFoundError,
    TwitterApiIoReader,
    XReaderError,
    XReaderNotConfiguredError,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def api_key(monkeypatch):
    monkeypatch.setattr(settings, "TWITTERAPI_IO_API_KEY", "twitterapi-test-key")


def _last_tweets() -> dict:
    return json.loads((FIXTURES / "twitterapi_io_last_tweets.json").read_text())


@respx.mock
async def test_keeps_original_posts_and_quotes_and_drops_replies_reposts_and_unreadable_posts():
    route = respx.get(TWITTERAPI_IO_LAST_TWEETS_URL).mock(
        return_value=httpx.Response(200, json=_last_tweets())
    )

    posts = await TwitterApiIoReader().fetch_recent_posts("levelsio")

    assert posts == [
        FetchedPost(
            post_id="1843000000000000006",
            text="shipped a new feature today, took 20 minutes",
            posted_at=datetime(2026, 10, 5, 18, 2, 11, tzinfo=timezone.utc),
        ),
        FetchedPost(
            post_id="1843000000000000005",
            text="this is the way",
            posted_at=datetime(2026, 10, 5, 12, 40, tzinfo=timezone.utc),
        ),
        FetchedPost(
            post_id="1843000000000000000",
            text="an id sent as a number",
            posted_at=datetime(2026, 10, 4, 23, 59, 59, tzinfo=timezone.utc),
        ),
    ]
    request = route.calls.last.request
    assert request.headers["x-api-key"] == "twitterapi-test-key"
    assert dict(request.url.params) == {"userName": "levelsio", "includeReplies": "false"}


@respx.mock
async def test_reads_tweets_at_the_top_level_of_the_body_too():
    body = _last_tweets()
    body["tweets"] = body.pop("data")["tweets"]
    respx.get(TWITTERAPI_IO_LAST_TWEETS_URL).mock(return_value=httpx.Response(200, json=body))

    posts = await TwitterApiIoReader().fetch_recent_posts("levelsio")

    assert len(posts) == 3


@respx.mock
async def test_an_empty_timeline_is_no_posts_not_an_unknown_handle():
    respx.get(TWITTERAPI_IO_LAST_TWEETS_URL).mock(
        return_value=httpx.Response(
            200, json={"status": "success", "data": {"tweets": []}, "has_next_page": False}
        )
    )

    assert await TwitterApiIoReader().fetch_recent_posts("quiet") == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"status": "error", "msg": "User not found"}),
        httpx.Response(400, json={"status": "error", "message": "user does not exist"}),
        httpx.Response(404, text="Not Found"),
    ],
)
@respx.mock
async def test_an_unknown_handle_is_handle_not_found(response):
    respx.get(TWITTERAPI_IO_LAST_TWEETS_URL).mock(return_value=response)

    with pytest.raises(HandleNotFoundError):
        await TwitterApiIoReader().fetch_recent_posts("nobody_here")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="Internal Server Error"),
        httpx.Response(429, json={"status": "error", "msg": "Too many requests"}),
        httpx.Response(200, json={"status": "error", "msg": "Insufficient credits"}),
        httpx.Response(200, text="<html>not json</html>"),
    ],
)
@respx.mock
async def test_any_other_failure_is_a_reader_error(response):
    respx.get(TWITTERAPI_IO_LAST_TWEETS_URL).mock(return_value=response)

    with pytest.raises(XReaderError) as raised:
        await TwitterApiIoReader().fetch_recent_posts("levelsio")

    assert not isinstance(raised.value, HandleNotFoundError)


@respx.mock
async def test_a_network_failure_is_a_reader_error():
    respx.get(TWITTERAPI_IO_LAST_TWEETS_URL).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(XReaderError):
        await TwitterApiIoReader().fetch_recent_posts("levelsio")


@respx.mock
async def test_without_the_key_it_fails_on_use_without_calling_twitterapi_io(monkeypatch):
    monkeypatch.setattr(settings, "TWITTERAPI_IO_API_KEY", None)
    route = respx.get(TWITTERAPI_IO_LAST_TWEETS_URL)

    with pytest.raises(XReaderNotConfiguredError, match="TWITTERAPI_IO_API_KEY"):
        await TwitterApiIoReader().fetch_recent_posts("levelsio")

    assert not route.called
