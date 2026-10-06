from unittest.mock import MagicMock

from app.core.posthog import PostHogClient


def test_disabled_client_is_a_noop():
    client = PostHogClient()  # test env has POSTHOG_ENABLED=false
    assert client.enabled is False
    client.capture("evt", "user_1", {"a": 1})
    client.identify("user_1", {"email": "a@example.com"})
    client.capture_exception(RuntimeError("boom"), properties={"error_id": "x"})
    client.shutdown()
    assert client.feature_enabled("flag", "user_1", default=True) is True


def test_capture_exception_swallows_sdk_errors():
    client = PostHogClient()
    sdk = MagicMock()
    sdk.capture_exception.side_effect = RuntimeError("sdk down")
    client._client = sdk
    client.capture_exception(ValueError("x"))
    sdk.capture_exception.assert_called_once()
