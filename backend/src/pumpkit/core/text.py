import re

_UNSTORABLE = re.compile(r"[\x00\ud800-\udfff]")


def drop_unstorable(text: str) -> str:
    """`text` without the NULs and unpaired surrogates Postgres can't store in TEXT."""
    return _UNSTORABLE.sub("", text)
