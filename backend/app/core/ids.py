from ulid import ULID


def ulid_with_prefix(prefix: str) -> str:
    """
    Generate a random ULID (Universally Unique Lexicographical Sortable Identifier) with a prefix.
    """
    return f"{prefix}_{str(ULID())}"
