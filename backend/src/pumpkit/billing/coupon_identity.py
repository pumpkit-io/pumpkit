import hashlib
import hmac

from pumpkit.core.config import Settings


def fingerprints(*, config: Settings, coupon_id: str, email: str, purpose: str) -> dict[str, str]:
    _, keys = config.coupon_identity_keys()
    message = "\0".join(("pumpkit-coupon", purpose, coupon_id, email.strip().lower())).encode()
    return {
        key_id: hmac.new(key, message, hashlib.sha256).hexdigest() for key_id, key in keys.items()
    }
