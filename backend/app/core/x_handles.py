import re

# What X allows in a handle. A space would not fail at the provider: it would read another account.
_HANDLE = re.compile(r"[A-Za-z0-9_]+")


def normalize_handle(value: str) -> str:
    """
    The form a handle is stored and compared under: no leading @ (what copying it off X
    gives you), lowercased. Raises `ValueError` for anything that isn't an X handle.
    """
    handle = value.strip().lstrip("@").strip()
    if not _HANDLE.fullmatch(handle):
        raise ValueError("An X handle holds only letters, digits and underscores.")
    return handle.lower()
