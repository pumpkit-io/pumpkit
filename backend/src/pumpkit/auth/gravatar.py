"""Where Gravatar serves the picture for an email address, if it has one."""

import hashlib

from pumpkit.core.photos import PHOTO_SIZE


def gravatar_url(email: str) -> str:
    """
    The Gravatar picture URL for `email`, sending Gravatar only its hash. `d=404` makes a missing
    Gravatar a 404 rather than Gravatar's default image, so it never becomes a Photo.
    """
    email_hash = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    return f"https://gravatar.com/avatar/{email_hash}?s={PHOTO_SIZE}&d=404"
