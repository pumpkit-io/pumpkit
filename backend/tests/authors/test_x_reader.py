import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

from pumpkit.authors.x_reader import (
    TWITTERAPI_IO_COMMUNITY_INFO_URL,
    TWITTERAPI_IO_LAST_TWEETS_URL,
    TWITTERAPI_IO_USER_INFO_URL,
    CommunityNotFoundError,
    FetchedCommunity,
    FetchedPost,
    FetchedProfile,
    HandleNotFoundError,
    HandleSuspendedError,
    TwitterApiIoReader,
    XReaderError,
    XReaderNotConfiguredError,
)
from pumpkit.core.config import settings

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

    recent = await TwitterApiIoReader().fetch_recent_posts("levelsio")

    assert recent.posts == [
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
async def test_reads_the_author_s_photo_from_their_posts():
    respx.get(TWITTERAPI_IO_LAST_TWEETS_URL).mock(
        return_value=httpx.Response(200, json=_last_tweets())
    )

    recent = await TwitterApiIoReader().fetch_recent_posts("levelsio")

    assert recent.photo_url == (
        "https://pbs.twimg.com/profile_images/1589756412078555136/YlXMBzhq_normal.jpg"
    )


@pytest.mark.parametrize("picture", [None, "", 42, "http://pbs.twimg.com/a_normal.jpg"])
@respx.mock
async def test_posts_without_a_usable_photo_read_as_no_photo(picture):
    body = _last_tweets()
    for tweet in body["data"]["tweets"]:
        if picture is None:
            tweet["author"].pop("profilePicture")
        else:
            tweet["author"]["profilePicture"] = picture
    respx.get(TWITTERAPI_IO_LAST_TWEETS_URL).mock(return_value=httpx.Response(200, json=body))

    recent = await TwitterApiIoReader().fetch_recent_posts("levelsio")

    assert recent.photo_url is None
    assert len(recent.posts) == 3


@respx.mock
async def test_reads_tweets_at_the_top_level_of_the_body_too():
    body = _last_tweets()
    body["tweets"] = body.pop("data")["tweets"]
    respx.get(TWITTERAPI_IO_LAST_TWEETS_URL).mock(return_value=httpx.Response(200, json=body))

    recent = await TwitterApiIoReader().fetch_recent_posts("levelsio")

    assert len(recent.posts) == 3


@respx.mock
async def test_an_empty_timeline_is_no_posts_not_an_unknown_handle():
    respx.get(TWITTERAPI_IO_LAST_TWEETS_URL).mock(
        return_value=httpx.Response(
            200, json={"status": "success", "data": {"tweets": []}, "has_next_page": False}
        )
    )

    recent = await TwitterApiIoReader().fetch_recent_posts("quiet")

    assert recent.posts == []
    assert recent.photo_url is None


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


COMMUNITY_ID = "1493446837214187523"


def _community_info() -> dict:
    return json.loads((FIXTURES / "twitterapi_io_community_info.json").read_text())


@respx.mock
async def test_fetches_a_community_s_name():
    route = respx.get(TWITTERAPI_IO_COMMUNITY_INFO_URL).mock(
        return_value=httpx.Response(200, json=_community_info())
    )

    community = await TwitterApiIoReader().fetch_community(COMMUNITY_ID)

    assert community == FetchedCommunity(id=COMMUNITY_ID, name="Build in Public")
    request = route.calls.last.request
    assert request.headers["x-api-key"] == "twitterapi-test-key"
    assert dict(request.url.params) == {"community_id": COMMUNITY_ID}


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, text="Not Found"),
        httpx.Response(200, json={"status": "error", "msg": "Community not found"}),
        httpx.Response(400, json={"error": 400, "message": "community does not exist"}),
        httpx.Response(200, json={"community_info": None, "status": "success", "msg": ""}),
        httpx.Response(200, json={"community_info": {}, "status": "success", "msg": ""}),
    ],
)
@respx.mock
async def test_an_unknown_community_is_community_not_found(response):
    respx.get(TWITTERAPI_IO_COMMUNITY_INFO_URL).mock(return_value=response)

    with pytest.raises(CommunityNotFoundError):
        await TwitterApiIoReader().fetch_community("1")


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
async def test_any_other_community_lookup_failure_is_a_reader_error(response):
    respx.get(TWITTERAPI_IO_COMMUNITY_INFO_URL).mock(return_value=response)

    with pytest.raises(XReaderError) as raised:
        await TwitterApiIoReader().fetch_community(COMMUNITY_ID)

    assert not isinstance(raised.value, CommunityNotFoundError)


@respx.mock
async def test_a_community_lookup_without_the_key_does_not_call_twitterapi_io(monkeypatch):
    monkeypatch.setattr(settings, "TWITTERAPI_IO_API_KEY", None)
    route = respx.get(TWITTERAPI_IO_COMMUNITY_INFO_URL)

    with pytest.raises(XReaderNotConfiguredError):
        await TwitterApiIoReader().fetch_community(COMMUNITY_ID)

    assert not route.called


def _user_info() -> dict:
    return json.loads((FIXTURES / "twitterapi_io_user_info.json").read_text())


@respx.mock
async def test_looks_a_handle_s_profile_up():
    route = respx.get(TWITTERAPI_IO_USER_INFO_URL).mock(
        return_value=httpx.Response(200, json=_user_info())
    )

    profile = await TwitterApiIoReader().look_up_profile("levelsio")

    assert profile == FetchedProfile(
        handle="levelsio",
        name="@levelsio",
        photo_url="https://pbs.twimg.com/profile_images/2077111020305162240/PwddgOau_normal.jpg",
        protected=False,
    )
    request = route.calls.last.request
    assert request.headers["x-api-key"] == "twitterapi-test-key"
    assert dict(request.url.params) == {"userName": "levelsio"}


@respx.mock
async def test_a_protected_account_s_profile_says_so():
    body = _user_info()
    body["data"]["protected"] = True
    respx.get(TWITTERAPI_IO_USER_INFO_URL).mock(return_value=httpx.Response(200, json=body))

    profile = await TwitterApiIoReader().look_up_profile("levelsio")

    assert profile.protected is True


@respx.mock
async def test_a_profile_without_a_usable_name_or_photo_reads_them_as_none():
    body = _user_info()
    body["data"]["name"] = "  "
    body["data"]["profilePicture"] = "http://pbs.twimg.com/a_normal.jpg"
    respx.get(TWITTERAPI_IO_USER_INFO_URL).mock(return_value=httpx.Response(200, json=body))

    profile = await TwitterApiIoReader().look_up_profile("levelsio")

    assert (profile.name, profile.photo_url) == (None, None)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"status": "error", "msg": "user not found", "data": None}),
        httpx.Response(404, text="Not Found"),
    ],
)
@respx.mock
async def test_an_unknown_handle_s_profile_is_handle_not_found(response):
    respx.get(TWITTERAPI_IO_USER_INFO_URL).mock(return_value=response)

    with pytest.raises(HandleNotFoundError) as raised:
        await TwitterApiIoReader().look_up_profile("nobody_here")

    assert not isinstance(raised.value, HandleSuspendedError)


@respx.mock
async def test_a_suspended_account_s_profile_is_handle_suspended():
    respx.get(TWITTERAPI_IO_USER_INFO_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "msg": "success",
                "data": {
                    "unavailable": True,
                    "message": "User is suspended",
                    "unavailableReason": "Suspended",
                },
            },
        )
    )

    with pytest.raises(HandleSuspendedError):
        await TwitterApiIoReader().look_up_profile("suspended_one")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="Internal Server Error"),
        httpx.Response(200, json={"status": "error", "msg": "Insufficient credits"}),
        httpx.Response(200, json={"status": "success", "msg": "success", "data": None}),
        httpx.Response(200, text="<html>not json</html>"),
    ],
)
@respx.mock
async def test_any_other_profile_failure_is_a_reader_error(response):
    respx.get(TWITTERAPI_IO_USER_INFO_URL).mock(return_value=response)

    with pytest.raises(XReaderError) as raised:
        await TwitterApiIoReader().look_up_profile("levelsio")

    assert not isinstance(raised.value, HandleNotFoundError)


@respx.mock
async def test_a_profile_lookup_without_the_key_fails_without_calling_twitterapi_io(monkeypatch):
    monkeypatch.setattr(settings, "TWITTERAPI_IO_API_KEY", None)
    route = respx.get(TWITTERAPI_IO_USER_INFO_URL)

    with pytest.raises(XReaderNotConfiguredError):
        await TwitterApiIoReader().look_up_profile("levelsio")

    assert not route.called


@respx.mock
async def test_reads_the_author_s_name_from_their_posts():
    respx.get(TWITTERAPI_IO_LAST_TWEETS_URL).mock(
        return_value=httpx.Response(200, json=_last_tweets())
    )

    recent = await TwitterApiIoReader().fetch_recent_posts("levelsio")

    assert recent.name == "@levelsio"
