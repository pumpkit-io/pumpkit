from datetime import datetime, timezone


def as_utc(value: datetime) -> datetime:
    """
    Return a datetime loaded from the database as an aware UTC value.

    Postgres returns aware datetimes; SQLite (tests) drops the offset. Values are
    always stored in UTC, so a naive one is UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
