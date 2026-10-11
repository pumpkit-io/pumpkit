from datetime import datetime, timezone


def as_utc(value: datetime) -> datetime:
    """
    Return a datetime loaded from the database as an aware UTC value.

    SQLite (tests) drops the offset Postgres keeps; values are stored in UTC, so naive is UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
