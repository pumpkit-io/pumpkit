"""
The steps of publishing a Scheduled post on X (ADR 0007), sequenced by `publishing`.
Flushes and never commits: `publishing` commits the claim and any rotated tokens before X.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional

from sqlalchemy.ext.asyncio import AsyncSession

import pumpkit.billing.service as subscriptions_service
import pumpkit.x_connection.service as x_connections_service
from pumpkit.core.analytics import posthog_client
from pumpkit.core.time import as_utc
from pumpkit.scheduling import service
from pumpkit.scheduling.models import ScheduledPost
from pumpkit.x_connection.models import XConnection
from pumpkit.x_connection.x_publisher import (
    XNotReceivedError,
    XPostRejectedError,
    XPublisher,
    XPublisherError,
    XPublisherNotConfiguredError,
    XRateLimitedError,
    XReconnectNeededError,
)

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
    "refused_by_x",
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
    "X didn't confirm this post. It may have been published. Check your X profile."
)
# X answers a Community post from a non-member with a 403, and can't be asked about membership.
COMMUNITY_MEMBERSHIP_HINT = (
    "Check that your X account is a member of this Community and allowed to post in it."
)

# Far longer than one call to X takes: a Scheduled post publishing this long lost its publisher.
STUCK_AFTER = timedelta(minutes=10)


@dataclass
class Failed(Exception):
    category: FailureCategory
    reason: str


async def fail_stuck(db: AsyncSession, *, now: datetime) -> list[str]:
    """Fail Scheduled posts a crashed publisher left in publishing: X may have taken them."""
    return await service.fail_stuck(
        db, publishing_since=now - STUCK_AFTER, reason=OUTCOME_UNKNOWN_REASON, now=now
    )


async def connection_to_publish_on(db: AsyncSession, scheduled_post: ScheduledPost) -> XConnection:
    """The X connection, row-locked until the next commit, or `Failed`."""
    if not await subscriptions_service.has_access(db, user_id=scheduled_post.user_id):
        raise Failed("not_subscribed", NOT_SUBSCRIBED_REASON)

    connection = await x_connections_service.lock_connection(db, user_id=scheduled_post.user_id)
    if connection is None or connection.x_user_id != scheduled_post.x_user_id:
        raise Failed("x_account_changed", X_ACCOUNT_CHANGED_REASON)
    if connection.needs_reconnect:
        raise Failed("reconnect_needed", RECONNECT_NEEDED_REASON)
    return connection


async def fresh_access_token(
    db: AsyncSession, publisher: XPublisher, connection: XConnection, *, now: datetime
) -> str:
    """
    Refreshed when near expiry. Flushes the rotated tokens, or the needs-reconnect flag before
    raising `Failed`; call it under the X connection's row lock.
    """
    if as_utc(connection.access_token_expires_at) - now > REFRESH_MARGIN:
        access_token = x_connections_service.access_token(connection)
        if not access_token:
            await x_connections_service.flag_needs_reconnect(db, connection, now=now)
            raise Failed("reconnect_needed", RECONNECT_NEEDED_REASON)
        return access_token

    refresh_token = x_connections_service.refresh_token(connection)
    if not refresh_token:
        await x_connections_service.flag_needs_reconnect(db, connection, now=now)
        raise Failed("reconnect_needed", RECONNECT_NEEDED_REASON)
    try:
        tokens = await publisher.refresh(refresh_token=refresh_token, now=now)
    except XReconnectNeededError:
        await x_connections_service.flag_needs_reconnect(db, connection, now=now)
        raise Failed("reconnect_needed", RECONNECT_NEEDED_REASON)
    except XPublisherError:
        raise Failed("x_unavailable", X_UNAVAILABLE_REASON)
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


async def call_x(publisher: XPublisher, scheduled_post: ScheduledPost, *, access_token: str) -> str:
    """X's post id, or `Failed`. A "reconnect_needed" one means X refused the access token."""
    try:
        return await publisher.publish(
            access_token=access_token,
            # TODO(#152): publish every Part as a chain; only the first goes out until then.
            text=scheduled_post.parts[0].text,
            community_id=scheduled_post.community_id,
            share_with_followers=scheduled_post.share_with_followers,
        )
    except XReconnectNeededError:
        raise Failed("reconnect_needed", RECONNECT_NEEDED_REASON)
    except (XRateLimitedError, XNotReceivedError, XPublisherNotConfiguredError):
        raise Failed("x_unavailable", X_UNAVAILABLE_REASON)
    except XPostRejectedError as rejected:
        reason = f"X refused the post: {rejected.message}"
        if scheduled_post.community_id and rejected.x_status == 403:
            reason = f"{reason} {COMMUNITY_MEMBERSHIP_HINT}"
        raise Failed("refused_by_x", reason)
    except XPublisherError:
        raise Failed("outcome_unknown", OUTCOME_UNKNOWN_REASON)


async def record_failure(
    db: AsyncSession, scheduled_post: ScheduledPost, failed: Failed, *, now: datetime
) -> bool:
    """
    Flushes Failed, or, for one X never took, back to scheduled with a backoff until
    `RETRY_WINDOW` is over. True when it became Failed.
    """
    next_attempt_at = _next_attempt_at(scheduled_post, now=now)
    if failed.category == "x_unavailable" and next_attempt_at:
        await service.release_for_retry(
            db, scheduled_post, next_attempt_at=next_attempt_at, now=now
        )
        return False
    await service.record_failed(db, scheduled_post, reason=failed.reason, now=now)
    return True


def _next_attempt_at(scheduled_post: ScheduledPost, *, now: datetime) -> Optional[datetime]:
    """Doubling from `FIRST_BACKOFF`, with one last try at the deadline; None after it."""
    deadline = as_utc(scheduled_post.publish_at) + RETRY_WINDOW
    if now >= deadline:
        return None
    return min(now + FIRST_BACKOFF * 2**scheduled_post.retry_count, deadline)


def capture_published(scheduled_post: ScheduledPost) -> None:
    properties: dict[str, object] = {
        "source": "final" if scheduled_post.source_version_id else "typed",
        "destination": "community" if scheduled_post.community_id else "profile",
    }
    if scheduled_post.community_id:
        properties["share_with_followers"] = scheduled_post.share_with_followers
    posthog_client.capture(
        "scheduled_post_published", distinct_id=scheduled_post.user_id, properties=properties
    )


def capture_failed(user_id: str, category: FailureCategory) -> None:
    posthog_client.capture(
        "scheduled_post_failed", distinct_id=user_id, properties={"reason": category}
    )
