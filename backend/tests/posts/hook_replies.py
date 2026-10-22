"""The hook call's scripted replies, for tests that write a first Version."""


def keep_hook() -> dict:
    """The hook call's answer that leaves the Draft as it is."""
    return {
        "current_hook_name": None,
        "mode": "keep",
        "replacing_hook_name": None,
        "replaced_text": None,
        "replacing_text": None,
    }
