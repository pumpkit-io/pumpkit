"""The hook call's scripted replies, for tests that write a first Version."""


def no_hook() -> dict:
    """The hook call's answer that writes no Hook, so the draft call gets no hook message."""
    return {"hook_name": None, "hook": None}
