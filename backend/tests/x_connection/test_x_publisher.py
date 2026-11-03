import asyncio
import base64
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from pumpkit.core.config import settings
from pumpkit.x_connection import x_publisher
from pumpkit.x_connection.x_publisher import (
    X_AUTHORIZE_URL,
    X_MEDIA_METADATA_URL,
    X_MEDIA_UPLOAD_URL,
    X_REVOKE_URL,
    X_TOKEN_URL,
    X_TWEETS_URL,
    X_USERS_ME_URL,
    OfficialXPublisher,
    XAccount,
    XMediaRefusedError,
    XMediaUnavailableError,
    XNotReceivedError,
    XOutcomeUnknownError,
    XPostRejectedError,
    XPublisherError,
    XPublisherNotConfiguredError,
    XRateLimitedError,
    XReconnectNeededError,
    XTokens,
    code_challenge_for,
    new_code_verifier,
)


@pytest.fixture(autouse=True)
def x_app(monkeypatch):
    monkeypatch.setattr(settings, "X_CLIENT_ID", "x-client-id")
    monkeypatch.setattr(settings, "X_CLIENT_SECRET", "x-client-secret")


def test_the_challenge_matches_the_rfc_7636_example():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"

    assert code_challenge_for(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_the_challenge_has_no_padding():
    assert "=" not in code_challenge_for("a")


def test_a_verifier_is_a_fresh_43_to_128_character_string():
    first, second = new_code_verifier(), new_code_verifier()

    assert 43 <= len(first) <= 128
    assert first != second


def test_the_authorize_url_asks_for_the_publishing_scopes_with_an_s256_challenge():
    url = OfficialXPublisher().build_authorize_url(state="the-state", code_challenge="chal")

    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == X_AUTHORIZE_URL
    assert {key: values[0] for key, values in parse_qs(parts.query).items()} == {
        "response_type": "code",
        "client_id": "x-client-id",
        "redirect_uri": "http://localhost:5173/oauth/x/callback",
        "scope": "tweet.read tweet.write users.read offline.access media.write",
        "state": "the-state",
        "code_challenge": "chal",
        "code_challenge_method": "S256",
    }


@pytest.mark.parametrize("missing", ["X_CLIENT_ID", "X_CLIENT_SECRET"])
def test_without_the_x_app_settings_it_fails_on_use_naming_them(monkeypatch, missing):
    monkeypatch.setattr(settings, missing, None)

    with pytest.raises(XPublisherNotConfiguredError, match="X_CLIENT_ID"):
        OfficialXPublisher().build_authorize_url(state="s", code_challenge="c")


NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
BASIC = "Basic " + base64.b64encode(b"x-client-id:x-client-secret").decode()


def _form(request: httpx.Request) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(request.content.decode()).items()}


def _token_body(**overrides) -> dict:
    body = {
        "token_type": "bearer",
        "access_token": "access-1",
        "refresh_token": "refresh-1",
        "expires_in": 7200,
        "scope": "tweet.read tweet.write users.read offline.access",
    }
    body.update(overrides)
    return {key: value for key, value in body.items() if value is not None}


@respx.mock
async def test_exchanging_a_code_sends_it_with_the_verifier_as_a_confidential_client():
    route = respx.post(X_TOKEN_URL).mock(return_value=httpx.Response(200, json=_token_body()))

    tokens = await OfficialXPublisher().exchange_code(
        code="the-code", code_verifier="the-verifier", now=NOW
    )

    assert tokens == XTokens(
        access_token="access-1",
        refresh_token="refresh-1",
        expires_at=NOW + timedelta(seconds=7200),
        scope="tweet.read tweet.write users.read offline.access",
    )
    request = route.calls.last.request
    assert request.headers["Authorization"] == BASIC
    assert _form(request) == {
        "grant_type": "authorization_code",
        "code": "the-code",
        "code_verifier": "the-verifier",
        "redirect_uri": "http://localhost:5173/oauth/x/callback",
    }


@respx.mock
async def test_the_expiry_is_stamped_from_expires_in():
    respx.post(X_TOKEN_URL).mock(return_value=httpx.Response(200, json=_token_body(expires_in=60)))

    tokens = await OfficialXPublisher().exchange_code(code="c", code_verifier="v", now=NOW)

    assert tokens.expires_at == NOW + timedelta(seconds=60)


@respx.mock
async def test_an_exchange_without_a_refresh_token_is_refused_naming_offline_access():
    respx.post(X_TOKEN_URL).mock(
        return_value=httpx.Response(200, json=_token_body(refresh_token=None))
    )

    with pytest.raises(XReconnectNeededError, match="offline.access"):
        await OfficialXPublisher().exchange_code(code="c", code_verifier="v", now=NOW)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(400, json={"error": "invalid_grant", "error_description": "bad code"}),
        httpx.Response(401, json={"error": "invalid_client"}),
    ],
)
@respx.mock
async def test_a_refused_grant_or_client_needs_a_reconnect(response):
    respx.post(X_TOKEN_URL).mock(return_value=response)

    with pytest.raises(XReconnectNeededError):
        await OfficialXPublisher().exchange_code(code="c", code_verifier="v", now=NOW)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, text="Service Unavailable"),
        httpx.Response(400, json={"error": "invalid_request"}),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"token_type": "bearer"}),
    ],
)
@respx.mock
async def test_any_other_token_failure_is_an_ordinary_error(response):
    respx.post(X_TOKEN_URL).mock(return_value=response)

    with pytest.raises(XPublisherError) as raised:
        await OfficialXPublisher().exchange_code(code="c", code_verifier="v", now=NOW)

    assert not isinstance(raised.value, XReconnectNeededError)


@respx.mock
async def test_a_network_failure_on_the_token_call_is_an_ordinary_error():
    respx.post(X_TOKEN_URL).mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(XPublisherError) as raised:
        await OfficialXPublisher().exchange_code(code="c", code_verifier="v", now=NOW)

    assert not isinstance(raised.value, XReconnectNeededError)


@respx.mock
async def test_reading_the_account_returns_its_id_handle_and_subscription_type():
    route = respx.get(X_USERS_ME_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"id": "42", "username": "ada", "subscription_type": "Premium"}},
        )
    )

    account = await OfficialXPublisher().fetch_account(access_token="access-1")

    assert account == XAccount(user_id="42", handle="ada", subscription_type="Premium")
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer access-1"
    assert request.url.params["user.fields"] == "subscription_type,profile_image_url"


@respx.mock
async def test_an_account_without_a_subscription_type_reads_as_none():
    respx.get(X_USERS_ME_URL).mock(
        return_value=httpx.Response(200, json={"data": {"id": "42", "username": "ada"}})
    )

    account = await OfficialXPublisher().fetch_account(access_token="access-1")

    assert account.subscription_type is None


@respx.mock
async def test_the_account_s_photo_is_read_in_its_larger_size():
    small = "https://pbs.twimg.com/profile_images/1/ada_normal.jpg"
    respx.get(X_USERS_ME_URL).mock(
        return_value=httpx.Response(
            200, json={"data": {"id": "42", "username": "ada", "profile_image_url": small}}
        )
    )

    account = await OfficialXPublisher().fetch_account(access_token="access-1")

    assert account.photo_url == "https://pbs.twimg.com/profile_images/1/ada_200x200.jpg"


@respx.mock
async def test_an_account_without_a_photo_reads_as_none():
    respx.get(X_USERS_ME_URL).mock(
        return_value=httpx.Response(200, json={"data": {"id": "42", "username": "ada"}})
    )

    account = await OfficialXPublisher().fetch_account(access_token="access-1")

    assert account.photo_url is None


@respx.mock
async def test_a_refused_token_when_reading_the_account_needs_a_reconnect():
    respx.get(X_USERS_ME_URL).mock(return_value=httpx.Response(401, json={"title": "Unauthorized"}))

    with pytest.raises(XReconnectNeededError):
        await OfficialXPublisher().fetch_account(access_token="access-1")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="oops"),
        httpx.Response(200, json={"data": {"username": "ada"}}),
        httpx.Response(200, text="not json"),
    ],
)
@respx.mock
async def test_an_unreadable_account_is_an_ordinary_error(response):
    respx.get(X_USERS_ME_URL).mock(return_value=response)

    with pytest.raises(XPublisherError) as raised:
        await OfficialXPublisher().fetch_account(access_token="access-1")

    assert not isinstance(raised.value, XReconnectNeededError)


@respx.mock
async def test_revoking_sends_the_refresh_token_as_a_confidential_client():
    route = respx.post(X_REVOKE_URL).mock(return_value=httpx.Response(200, json={"revoked": True}))

    await OfficialXPublisher().revoke(token="refresh-1", token_type_hint="refresh_token")

    request = route.calls.last.request
    assert request.headers["Authorization"] == BASIC
    assert _form(request) == {"token": "refresh-1", "token_type_hint": "refresh_token"}


@pytest.mark.parametrize(
    "mock",
    [
        {"return_value": httpx.Response(503, text="down")},
        {"side_effect": httpx.ConnectError("refused")},
    ],
)
@respx.mock
async def test_a_failed_revoke_is_an_error(mock):
    respx.post(X_REVOKE_URL).mock(**mock)

    with pytest.raises(XPublisherError):
        await OfficialXPublisher().revoke(token="refresh-1", token_type_hint="refresh_token")


@respx.mock
async def test_refreshing_sends_the_refresh_token_as_a_confidential_client():
    route = respx.post(X_TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json=_token_body(access_token="access-2", refresh_token="refresh-2")
        )
    )

    tokens = await OfficialXPublisher().refresh(refresh_token="refresh-1", now=NOW)

    assert tokens == XTokens(
        access_token="access-2",
        refresh_token="refresh-2",
        expires_at=NOW + timedelta(seconds=7200),
        scope="tweet.read tweet.write users.read offline.access",
    )
    request = route.calls.last.request
    assert request.headers["Authorization"] == BASIC
    assert _form(request) == {"grant_type": "refresh_token", "refresh_token": "refresh-1"}


@respx.mock
async def test_a_refresh_that_leaves_out_the_refresh_token_keeps_the_old_one():
    respx.post(X_TOKEN_URL).mock(
        return_value=httpx.Response(200, json=_token_body(refresh_token=None))
    )

    tokens = await OfficialXPublisher().refresh(refresh_token="refresh-1", now=NOW)

    assert tokens.refresh_token == "refresh-1"


@respx.mock
async def test_a_dead_refresh_token_needs_a_reconnect():
    respx.post(X_TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))

    with pytest.raises(XReconnectNeededError):
        await OfficialXPublisher().refresh(refresh_token="refresh-1", now=NOW)


@respx.mock
async def test_a_server_side_refresh_failure_is_an_ordinary_error():
    respx.post(X_TOKEN_URL).mock(return_value=httpx.Response(503, text="down"))

    with pytest.raises(XPublisherError) as raised:
        await OfficialXPublisher().refresh(refresh_token="refresh-1", now=NOW)

    assert not isinstance(raised.value, XReconnectNeededError)


@respx.mock
async def test_publishing_sends_the_text_with_the_access_token_and_returns_the_post_id():
    route = respx.post(X_TWEETS_URL).mock(
        return_value=httpx.Response(201, json={"data": {"id": "1890", "text": "Hello X"}})
    )

    post_id = await OfficialXPublisher().publish(access_token="access-1", text="Hello X")

    assert post_id == "1890"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer access-1"
    assert json.loads(request.content) == {"text": "Hello X"}


@respx.mock
async def test_publishing_a_reply_names_the_post_it_replies_to():
    route = respx.post(X_TWEETS_URL).mock(
        return_value=httpx.Response(201, json={"data": {"id": "1891", "text": "Part 2"}})
    )

    post_id = await OfficialXPublisher().publish(
        access_token="access-1", text="Part 2", reply_to="1890"
    )

    assert post_id == "1891"
    assert json.loads(route.calls.last.request.content) == {
        "text": "Part 2",
        "reply": {"in_reply_to_tweet_id": "1890"},
    }


@pytest.mark.parametrize("share_with_followers", [True, False])
@respx.mock
async def test_publishing_into_a_community_names_it_and_whether_followers_see_it_too(
    share_with_followers,
):
    route = respx.post(X_TWEETS_URL).mock(
        return_value=httpx.Response(201, json={"data": {"id": "1890", "text": "Hello X"}})
    )

    post_id = await OfficialXPublisher().publish(
        access_token="access-1",
        text="Hello X",
        community_id="1493446837214187523",
        share_with_followers=share_with_followers,
    )

    assert post_id == "1890"
    assert json.loads(route.calls.last.request.content) == {
        "text": "Hello X",
        "community_id": "1493446837214187523",
        "share_with_followers": share_with_followers,
    }


@pytest.mark.parametrize("share_with_followers", [True, False])
@respx.mock
async def test_a_reply_in_a_community_names_only_the_post_it_replies_to(share_with_followers):
    route = respx.post(X_TWEETS_URL).mock(
        return_value=httpx.Response(201, json={"data": {"id": "1891", "text": "Part 2"}})
    )

    post_id = await OfficialXPublisher().publish(
        access_token="access-1",
        text="Part 2",
        community_id="1493446837214187523",
        share_with_followers=share_with_followers,
        reply_to="1890",
    )

    assert post_id == "1891"
    assert json.loads(route.calls.last.request.content) == {
        "text": "Part 2",
        "reply": {"in_reply_to_tweet_id": "1890"},
    }


@pytest.mark.parametrize(
    "body",
    [
        {"detail": "You are not allowed to create a Tweet with duplicate content."},
        {"errors": [{"message": "You are not allowed to create a Tweet with duplicate content."}]},
    ],
)
@respx.mock
async def test_a_refused_post_carries_x_s_own_words(body):
    respx.post(X_TWEETS_URL).mock(return_value=httpx.Response(403, json=body))

    with pytest.raises(XPostRejectedError) as raised:
        await OfficialXPublisher().publish(access_token="access-1", text="Hello X")

    assert raised.value.message == "You are not allowed to create a Tweet with duplicate content."


@pytest.mark.parametrize("status", [400, 403, 404])
@respx.mock
async def test_a_refused_post_keeps_x_s_status(status):
    respx.post(X_TWEETS_URL).mock(
        return_value=httpx.Response(
            status, json={"detail": "You do not have permission to create this Tweet."}
        )
    )

    with pytest.raises(XPostRejectedError) as raised:
        await OfficialXPublisher().publish(
            access_token="access-1", text="Hello X", community_id="1493446837214187523"
        )

    assert raised.value.x_status == status


@respx.mock
async def test_a_refusal_without_a_readable_body_still_says_what_x_answered():
    respx.post(X_TWEETS_URL).mock(return_value=httpx.Response(400, text="Bad Request"))

    with pytest.raises(XPostRejectedError) as raised:
        await OfficialXPublisher().publish(access_token="access-1", text="Hello X")

    assert raised.value.message == "Bad Request"


@respx.mock
async def test_an_unauthorized_post_needs_a_reconnect():
    respx.post(X_TWEETS_URL).mock(return_value=httpx.Response(401, json={"title": "Unauthorized"}))

    with pytest.raises(XReconnectNeededError):
        await OfficialXPublisher().publish(access_token="access-1", text="Hello X")


@respx.mock
async def test_a_rate_limit_is_reported_and_not_retried():
    route = respx.post(X_TWEETS_URL).mock(return_value=httpx.Response(429, json={}))

    with pytest.raises(XRateLimitedError):
        await OfficialXPublisher().publish(access_token="access-1", text="Hello X")

    assert route.call_count == 1


@pytest.mark.parametrize(
    "error", [httpx.ConnectError("refused"), httpx.ConnectTimeout("slow"), httpx.PoolTimeout("")]
)
@respx.mock
async def test_a_request_that_never_reached_x_is_reported_as_not_received(error):
    respx.post(X_TWEETS_URL).mock(side_effect=error)

    with pytest.raises(XNotReceivedError):
        await OfficialXPublisher().publish(access_token="access-1", text="Hello X")


@pytest.mark.parametrize(
    "mock",
    [
        {"side_effect": httpx.ReadTimeout("slow")},
        {"side_effect": httpx.RemoteProtocolError("dropped")},
        {"return_value": httpx.Response(500, text="oops")},
        {"return_value": httpx.Response(503, text="over capacity")},
        {"return_value": httpx.Response(201, json={"data": {}})},
        {"return_value": httpx.Response(200, text="not json")},
    ],
)
@respx.mock
async def test_a_post_x_may_have_taken_is_reported_as_outcome_unknown(mock):
    respx.post(X_TWEETS_URL).mock(**mock)

    with pytest.raises(XOutcomeUnknownError):
        await OfficialXPublisher().publish(access_token="access-1", text="Hello X")


# X's answers as its media upload guide shows them (docs.x.com, Nov 2026).
MEDIA_ID = "1880028106020515840"
INITIALIZED = {"data": {"id": MEDIA_ID, "media_key": f"3_{MEDIA_ID}", "expires_after_secs": 86400}}
FINALIZED = {
    "data": {
        "id": MEDIA_ID,
        "media_key": f"3_{MEDIA_ID}",
        "size": 3,
        "expires_after_secs": 86400,
    }
}


def _processing(state: str, **info) -> dict:
    return {
        "data": {
            **FINALIZED["data"],
            "processing_info": {"state": state, "check_after_secs": 1, **info},
        }
    }


def _upload_routes(finalized: dict = FINALIZED) -> tuple[respx.Route, respx.Route, respx.Route]:
    return (
        respx.post(f"{X_MEDIA_UPLOAD_URL}/initialize").mock(
            return_value=httpx.Response(200, json=INITIALIZED)
        ),
        respx.post(f"{X_MEDIA_UPLOAD_URL}/{MEDIA_ID}/append").mock(
            return_value=httpx.Response(204)
        ),
        respx.post(f"{X_MEDIA_UPLOAD_URL}/{MEDIA_ID}/finalize").mock(
            return_value=httpx.Response(200, json=finalized)
        ),
    )


async def _upload(data: bytes = b"png", tokens: Optional[list[str]] = None, **fields) -> str:
    sent = iter(tokens) if tokens is not None else None

    async def token_for_call() -> str:
        return next(sent) if sent is not None else "access-1"

    return await OfficialXPublisher().upload_media(
        token_for_call=token_for_call,
        source=io.BytesIO(data),
        byte_size=len(data),
        content_type=fields.get("content_type", "image/png"),
        category=fields.get("category", "tweet_image"),
    )


@pytest.fixture
def no_waiting(monkeypatch) -> list[float]:
    waits: list[float] = []

    async def _sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(x_publisher.asyncio, "sleep", _sleep)
    return waits


@respx.mock
async def test_an_image_is_uploaded_in_chunks_and_its_media_id_returned():
    initialize, append, finalize = _upload_routes()

    media_id = await _upload(b"png")

    assert media_id == MEDIA_ID
    started = initialize.calls.last.request
    assert started.headers["Authorization"] == "Bearer access-1"
    assert json.loads(started.content) == {
        "media_type": "image/png",
        "total_bytes": 3,
        "media_category": "tweet_image",
    }
    sent = append.calls.last.request
    assert sent.headers["Authorization"] == "Bearer access-1"
    assert b'name="segment_index"\r\n\r\n0\r\n' in sent.content
    assert b'name="media"' in sent.content and b"\r\n\r\npng\r\n" in sent.content
    assert finalize.calls.last.request.headers["Authorization"] == "Bearer access-1"


@respx.mock
async def test_a_file_over_one_chunk_goes_in_numbered_segments():
    _, append, _ = _upload_routes()

    await _upload(b"x" * (5 * 1024 * 1024))

    segments = [call.request.content for call in append.calls]
    assert len(segments) == 2
    assert b'name="segment_index"\r\n\r\n0\r\n' in segments[0]
    assert b'name="segment_index"\r\n\r\n1\r\n' in segments[1]


@respx.mock
async def test_an_upload_x_processes_is_polled_until_it_succeeds(no_waiting):
    _upload_routes(_processing("pending"))
    status = respx.get(X_MEDIA_UPLOAD_URL).mock(
        side_effect=[
            httpx.Response(200, json=_processing("in_progress", progress_percent=40)),
            httpx.Response(200, json=_processing("succeeded", progress_percent=100)),
        ]
    )

    assert await _upload(category="tweet_video", content_type="video/mp4") == MEDIA_ID

    assert [dict(call.request.url.params) for call in status.calls] == [
        {"command": "STATUS", "media_id": MEDIA_ID}
    ] * 2
    assert no_waiting == [1.0, 1.0]


@respx.mock
async def test_each_call_of_an_upload_sends_the_token_asked_for_it(no_waiting):
    initialize, append, finalize = _upload_routes(_processing("pending"))
    status = respx.get(X_MEDIA_UPLOAD_URL).mock(
        return_value=httpx.Response(200, json=_processing("succeeded"))
    )

    await _upload(
        b"x" * (5 * 1024 * 1024),
        tokens=["t-init", "t-chunk-0", "t-chunk-1", "t-finalize", "t-status"],
        category="tweet_video",
        content_type="video/mp4",
    )

    sent = [
        call.request.headers["Authorization"]
        for route in (initialize, append, finalize, status)
        for call in route.calls
    ]
    assert sent == [
        "Bearer t-init",
        "Bearer t-chunk-0",
        "Bearer t-chunk-1",
        "Bearer t-finalize",
        "Bearer t-status",
    ]


@respx.mock
async def test_a_video_x_processes_for_minutes_is_waited_on_in_short_polls(no_waiting):
    _upload_routes(_processing("pending", check_after_secs=300))
    respx.get(X_MEDIA_UPLOAD_URL).mock(
        side_effect=[
            *[httpx.Response(200, json=_processing("in_progress", check_after_secs=300))] * 9,
            httpx.Response(200, json=_processing("succeeded")),
        ]
    )

    assert await _upload(category="tweet_video", content_type="video/mp4") == MEDIA_ID

    assert no_waiting == [60.0] * 10


@respx.mock
async def test_an_image_x_is_still_processing_after_3_minutes_is_a_passing_failure(no_waiting):
    _upload_routes(_processing("pending", check_after_secs=60))
    respx.get(X_MEDIA_UPLOAD_URL).mock(
        return_value=httpx.Response(200, json=_processing("in_progress", check_after_secs=60))
    )

    with pytest.raises(XMediaUnavailableError):
        await _upload()

    assert sum(no_waiting) == 180


@respx.mock
async def test_processing_x_fails_is_a_refusal_with_its_reason(no_waiting):
    _upload_routes(_processing("pending"))
    respx.get(X_MEDIA_UPLOAD_URL).mock(
        return_value=httpx.Response(
            200,
            json=_processing("failed", error={"code": 1, "message": "Unsupported video."}),
        )
    )

    with pytest.raises(XMediaRefusedError) as refused:
        await _upload(category="tweet_video", content_type="video/mp4")

    assert refused.value.message == "Unsupported video."


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(401, json={"title": "Unauthorized"}), XReconnectNeededError),
        (httpx.Response(429, json={"title": "Too Many Requests"}), XRateLimitedError),
        (httpx.Response(503, json={"title": "Service Unavailable"}), XMediaUnavailableError),
    ],
)
@respx.mock
async def test_an_upload_x_answers_with_an_error_status_says_what_kind(response, error):
    respx.post(f"{X_MEDIA_UPLOAD_URL}/initialize").mock(return_value=response)

    with pytest.raises(error):
        await _upload()


@respx.mock
async def test_an_upload_x_refuses_carries_xs_own_words():
    _, append, _ = _upload_routes()
    append.mock(
        return_value=httpx.Response(
            400,
            json={
                "errors": [{"message": "media type unrecognized."}],
                "title": "Invalid Request",
                "type": "https://api.x.com/2/problems/invalid-request",
            },
        )
    )

    with pytest.raises(XMediaRefusedError) as refused:
        await _upload()

    assert refused.value.x_status == 400
    assert refused.value.message == "media type unrecognized."


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (httpx.ConnectError("refused"), XNotReceivedError),
        (httpx.ReadTimeout("slow"), XMediaUnavailableError),
    ],
)
@respx.mock
async def test_an_upload_x_never_answers_publishes_nothing(side_effect, error):
    respx.post(f"{X_MEDIA_UPLOAD_URL}/initialize").mock(side_effect=side_effect)

    with pytest.raises(error):
        await _upload()


@respx.mock
async def test_a_chunk_still_sending_at_its_time_limit_is_a_passing_failure(monkeypatch):
    monkeypatch.setattr(x_publisher, "_APPEND_LIMIT_SECONDS", 0.05)
    _, append, _ = _upload_routes()

    async def slow_uplink(request: httpx.Request) -> httpx.Response:
        await asyncio.Event().wait()
        return httpx.Response(204)

    append.mock(side_effect=slow_uplink)

    with pytest.raises(XMediaUnavailableError):
        await _upload()


@respx.mock
async def test_publishing_with_media_sends_their_ids_under_the_text():
    route = respx.post(X_TWEETS_URL).mock(
        return_value=httpx.Response(201, json={"data": {"id": "1890", "text": "Look"}})
    )

    await OfficialXPublisher().publish(
        access_token="access-1", text="Look", media_ids=["1880", "1881"]
    )

    assert json.loads(route.calls.last.request.content) == {
        "text": "Look",
        "media": {"media_ids": ["1880", "1881"]},
    }


async def _set_alt_text(alt_text: str = "Gulls over the harbour.") -> None:
    await OfficialXPublisher().set_alt_text(
        access_token="access-1", media_id=MEDIA_ID, alt_text=alt_text
    )


@respx.mock
async def test_alt_text_is_sent_as_the_uploads_metadata():
    route = respx.post(X_MEDIA_METADATA_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": {"id": MEDIA_ID, "associated_metadata": {}}},
        )
    )

    await _set_alt_text()

    sent = route.calls.last.request
    assert sent.headers["Authorization"] == "Bearer access-1"
    assert json.loads(sent.content) == {
        "id": MEDIA_ID,
        "metadata": {"alt_text": {"text": "Gulls over the harbour."}},
    }


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(401, json={"title": "Unauthorized"}), XReconnectNeededError),
        (httpx.Response(429, json={"title": "Too Many Requests"}), XRateLimitedError),
        (httpx.Response(503, json={"title": "Service Unavailable"}), XMediaUnavailableError),
        (
            httpx.Response(400, json={"errors": [{"message": "alt text too long."}]}),
            XMediaRefusedError,
        ),
    ],
)
@respx.mock
async def test_alt_text_x_answers_with_an_error_status_says_what_kind(response, error):
    respx.post(X_MEDIA_METADATA_URL).mock(return_value=response)

    with pytest.raises(error):
        await _set_alt_text()


@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (httpx.ConnectError("refused"), XNotReceivedError),
        (httpx.ReadTimeout("slow"), XMediaUnavailableError),
    ],
)
@respx.mock
async def test_alt_text_x_never_answers_is_a_passing_failure(side_effect, error):
    respx.post(X_MEDIA_METADATA_URL).mock(side_effect=side_effect)

    with pytest.raises(error):
        await _set_alt_text()
