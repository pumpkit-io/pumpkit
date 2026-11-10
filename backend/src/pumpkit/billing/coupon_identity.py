import hashlib
import hmac

from pumpkit.core.config import Settings


def fingerprints(*, config: Settings, coupon_id: str, email: str, purpose: str) -> dict[str, str]:
    return _fingerprints(
        config=config, coupon_id=coupon_id, identity=email.strip().lower(), purpose=purpose
    )


def x_fingerprints(*, config: Settings, coupon_id: str, x_user_id: str) -> dict[str, str]:
    return _fingerprints(
        config=config, coupon_id=coupon_id, identity=x_user_id, purpose="claim-x-account"
    )


def _fingerprints(
    *, config: Settings, coupon_id: str, identity: str, purpose: str
) -> dict[str, str]:
    _, keys = config.coupon_identity_keys()
    message = "\0".join(("pumpkit-coupon", purpose, coupon_id, identity)).encode()
    return {
        key_id: hmac.new(key, message, hashlib.sha256).hexdigest() for key_id, key in keys.items()
    }
