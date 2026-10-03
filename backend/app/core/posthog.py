from __future__ import annotations

from typing import Any, Mapping, Optional

from posthog import Posthog

from app.core.config import settings
from app.core.logger import logger


class PostHogClient:
    """
    Async-safe wrapper around the PostHog Python SDK.

    The Personal API Key enables *local evaluation* of feature flags — the SDK
    polls flag definitions in the background, so `feature_enabled()` never blocks
    on a network round-trip from a request handler.

    All events are auto-tagged with `env=settings.ENV` so a single PostHog project
    can host local/dev/staging/prod data without polluting product metrics.
    """

    def __init__(self) -> None:
        self._client: Optional[Posthog] = None
        self._enabled = bool(settings.POSTHOG_ENABLED and settings.POSTHOG_PROJECT_API_KEY)
        if not self._enabled:
            logger.info("PostHog disabled (POSTHOG_ENABLED=false or missing project key)")
            return

        client = Posthog(
            project_api_key=settings.POSTHOG_PROJECT_API_KEY,
            host=settings.POSTHOG_HOST,
            personal_api_key=settings.POSTHOG_PERSONAL_API_KEY or None,
        )
        # Stamp every event server-side so we can slice by environment in PostHog.
        client.super_properties = {"env": settings.ENV}
        self._client = client

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def client(self) -> Optional[Posthog]:
        return self._client

    def capture(
        self,
        event: str,
        distinct_id: str,
        properties: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if not self._client:
            return
        self._client.capture(
            distinct_id=distinct_id,
            event=event,
            properties=dict(properties) if properties else None,
        )

    def identify(
        self,
        distinct_id: str,
        properties: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Set/update person properties for a known user.

        SDK v7 removed `identify()` in favour of `set()`/`set_once()` —
        the semantics differ from posthog-js (which still merges anonymous
        sessions on identify). On the server we don't have anonymous
        sessions, so `set()` is the right primitive for "this is who they
        are" attribution.
        """
        if not self._client:
            return
        self._client.set(
            distinct_id=distinct_id,
            properties=dict(properties) if properties else None,
        )

    def feature_enabled(
        self,
        key: str,
        distinct_id: str,
        *,
        default: bool = False,
        person_properties: Optional[Mapping[str, Any]] = None,
    ) -> bool:
        if not self._client:
            return default
        try:
            result = self._client.feature_enabled(
                key,
                distinct_id,
                person_properties=dict(person_properties) if person_properties else None,
            )
        except Exception:
            # Never fail a request because PostHog had a hiccup.
            logger.exception("PostHog feature flag eval failed for key=%s", key)
            return default
        return bool(result) if result is not None else default

    def capture_exception(
        self,
        exc: BaseException,
        *,
        distinct_id: Optional[str] = None,
        properties: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if not self._client:
            return
        try:
            self._client.capture_exception(
                exc,
                distinct_id=distinct_id,
                properties=dict(properties) if properties else None,
            )
        except Exception:
            logger.exception("PostHog capture_exception failed")

    def shutdown(self) -> None:
        """Flush buffered events and stop background threads. Idempotent."""
        if not self._client:
            return
        try:
            self._client.shutdown()
        except Exception:
            logger.exception("PostHog shutdown failed")


posthog_client = PostHogClient()
