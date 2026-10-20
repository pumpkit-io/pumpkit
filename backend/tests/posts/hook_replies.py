"""The hook call's scripted replies, for tests that write a first Version."""


def keep_hook() -> dict:
    """The hook call's answer that leaves the Draft as it is."""
    return {"hook_name": "none", "mode": "keep", "replaced_opening": "", "hook": ""}
