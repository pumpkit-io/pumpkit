"""
Publishing one Scheduled post on X, shared by Post now and the publisher (ADR 0007).

The caller claims the Scheduled post into publishing and commits that before anything
reaches X, so X is called at most once for it. `publish_claimed` then refreshes the X
connection's access token if needed, checks the User is Subscribed and still connected to
the X account the Scheduled post targets, calls X once, and records Published or Failed (or,
for the publisher, puts one X never took back in scheduled). It commits as it goes, so it
takes a session no other work shares.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional

from sqlalchemy.ext.asyncio import AsyncSession

import app.api.services.scheduled_posts as scheduled_posts_service
import app.api.services.subscriptions as subscriptions_service
import app.api.services.x_connections as x_connections_service
from app.core.datetimes import as_utc
from app.core.posthog import posthog_client
from app.core.x_publisher import (
    XNotReceivedError,
    XPostRejectedError,
    XPublisher,
    XPublisherError,
    XPublisherNotConfiguredError,
    XRateLimitedError,
    XReconnectNeededError,
)
from app.db.models import ScheduledPost, XConnection

# Refresh an access token this close to expiry, so it can't lapse during the call to X.
REFRESH_MARGIN = timedelta(minutes=5)

# A Scheduled post X never took (429, refused connection) is retried this long after its
# publish time, then Failed. Calling X again is safe only because X surely didn't publish it.
RETRY_WINDOW = timedelta(minutes=15)
FIRST_BACKOFF = timedelta(minutes=1)

# The analytics reason category of a Failed Scheduled post.
FailureCategory = Literal[
    "not_subscribed",
    "x_account_changed",
    "reconnect_needed",
    "x_unavailable",
    "rejected",
    "outcome_unknown",
]

NOT_SUBSCRIBED_REASON = "Not published: your Subscription had ended. Subscribe, then reschedule it."
X_ACCOUNT_CHANGED_REASON = (
    "Not published: the X account it was for is no longer connected to Pumpkit."
)
RECONNECT_NEEDED_REASON = (
    "Not published: X no longer accepts Pumpkit's access to your account. Reconnect X, then "
    "reschedule it."
)
X_UNAVAILABLE_REASON = "Not published: X was busy or unreachable. Try again in a few minutes."
OUTCOME_UNKNOWN_REASON = (
    "X didn't confirm this post. It may have been published, check your X profile."
)


@dataclass
class _Failed(Exception):
    category: FailureCategory
    reason: str


async def publish_scheduled_post(
    db: AsyncSession, publisher: XPublisher, *, scheduled_post_id: str, now: datetime
) -> bool:
    """
    Post now: publish the Scheduled post if it is scheduled, recording Published or Failed,
    without retrying. False when it wasn't scheduled, for instance because another caller
    claimed it first.
    """
    claimed = await scheduled_posts_service.claim(db, scheduled_post_id=scheduled_post_id, now=now)
    # Commit the claim before calling X: from here on, no other caller can publish it.
    await db.commit()
    if not claimed:
        return False
    await publish_claimed(db, publisher, scheduled_post_id=scheduled_post_id, now=now)
    return True


async def publish_claimed(
    db: AsyncSession,
    publisher: XPublisher,
    *,
    scheduled_post_id: str,
    now: datetime,
) -> None:
    """One X never took goes back to scheduled with a backoff until `RETRY_WINDOW` is over."""
    scheduled_post = await scheduled_posts_service.get(db, scheduled_post_id=scheduled_post_id)
    assert scheduled_post is not None

    try:
        x_post_id = await _publish(db, publisher, scheduled_post, now=now)
    except _Failed as failed:
        next_attempt_at = _next_attempt_at(scheduled_post, now=now)
        if failed.category == "x_unavailable" and next_attempt_at:
            await scheduled_posts_service.release_for_retry(
                db, scheduled_post, next_attempt_at=next_attempt_at, now=now
            )
            await db.commit()
            return
        await scheduled_posts_service.record_failed(
            db, scheduled_post, reason=failed.reason, now=now
        )
        await db.commit()
        posthog_client.capture(
            "scheduled_post_failed",
            distinct_id=scheduled_post.user_id,
            properties={"reason": failed.category},
        )
        return

    await scheduled_posts_service.record_published(db, scheduled_post, x_post_id=x_post_id, now=now)
    await db.commit()
    posthog_client.capture(
        "scheduled_post_published",
        distinct_id=scheduled_post.user_id,
        properties={"source": "final" if scheduled_post.source_version_id else "typed"},
    )


def _next_attempt_at(scheduled_post: ScheduledPost, *, now: datetime) -> Optional[datetime]:
    """
    When to try again after X didn't take it: doubling from `FIRST_BACKOFF`, with one last try
    at the end of the retry window. None once the window is over.
    """
    deadline = as_utc(scheduled_post.publish_at) + RETRY_WINDOW
    if now >= deadline:
        return None
    return min(now + FIRST_BACKOFF * 2**scheduled_post.retry_count, deadline)


async def _publish(
    db: AsyncSession, publisher: XPublisher, scheduled_post: ScheduledPost, *, now: datetime
) -> str:
    """X's post id, or `_Failed`. The caller commits whatever it flushed, either way."""
    subscription = await subscriptions_service.get_user_subscription(
        db, user_id=scheduled_post.user_id
    )
    if not subscriptions_service.is_subscribed(subscription):
        raise _Failed("not_subscribed", NOT_SUBSCRIBED_REASON)

    connection = await x_connections_service.lock_connection(db, user_id=scheduled_post.user_id)
    if connection is None or connection.x_user_id != scheduled_post.x_user_id:
        raise _Failed("x_account_changed", X_ACCOUNT_CHANGED_REASON)
    if connection.needs_reconnect:
        raise _Failed("reconnect_needed", RECONNECT_NEEDED_REASON)

    access_token = await _fresh_access_token(db, publisher, connection, now=now)
    # Commit the rotated tokens, or end the read, before the call to X: it releases the lock.
    await db.commit()

    try:
        return await publisher.publish(access_token=access_token, text=scheduled_post.text)
    except XReconnectNeededError:
        await x_connections_service.flag_needs_reconnect(db, connection, now=now)
        raise _Failed("reconnect_needed", RECONNECT_NEEDED_REASON)
    except (XRateLimitedError, XNotReceivedError, XPublisherNotConfiguredError):
        raise _Failed("x_unavailable", X_UNAVAILABLE_REASON)
    except XPostRejectedError as rejected:
        raise _Failed("rejected", f"X refused the post: {rejected.message}")
    except XPublisherError:
        raise _Failed("outcome_unknown", OUTCOME_UNKNOWN_REASON)


async def _fresh_access_token(
    db: AsyncSession, publisher: XPublisher, connection: XConnection, *, now: datetime
) -> str:
    """
    An access token good for the call to X, refreshed under the X connection's row lock when
    it is near expiry. The rotated tokens are flushed for the caller to commit before use.
    """
    if as_utc(connection.access_token_expires_at) - now > REFRESH_MARGIN:
        access_token = x_connections_service.access_token(connection)
        if not access_token:
            await x_connections_service.flag_needs_reconnect(db, connection, now=now)
            raise _Failed("reconnect_needed", RECONNECT_NEEDED_REASON)
        return access_token

    refresh_token = x_connections_service.refresh_token(connection)
    if not refresh_token:
        await x_connections_service.flag_needs_reconnect(db, connection, now=now)
        raise _Failed("reconnect_needed", RECONNECT_NEEDED_REASON)
    try:
        tokens = await publisher.refresh(refresh_token=refresh_token, now=now)
    except XReconnectNeededError:
        await x_connections_service.flag_needs_reconnect(db, connection, now=now)
        raise _Failed("reconnect_needed", RECONNECT_NEEDED_REASON)
    except XPublisherError:
        raise _Failed("x_unavailable", X_UNAVAILABLE_REASON)
    await x_connections_service.save_tokens(db, connection, tokens=tokens, now=now)
    try:
        account = await publisher.fetch_account(access_token=tokens.access_token)
    except XPublisherError:
        # The last-read subscription_type stands until the next refresh; the publish goes on.
        return tokens.access_token
    await x_connections_service.save_subscription_type(
        db, connection, subscription_type=account.subscription_type, now=now
    )
    return tokens.access_token
