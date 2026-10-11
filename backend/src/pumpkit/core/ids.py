from ulid import ULID


def ulid_with_prefix(prefix: str) -> str:
    return f"{prefix}_{str(ULID())}"
