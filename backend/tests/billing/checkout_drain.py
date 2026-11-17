"""Operator CLI fixtures backed by reviewed controlled-provider evidence."""

import hashlib
import json
from io import StringIO

from pumpkit.billing.checkout_drain import run_cli


async def drain(sessions, gateway, args, *, clock):
    out = StringIO()
    code = await run_cli(args, sessions=sessions, gateway=gateway, stdout=out, clock=clock)
    return code, json.loads(out.getvalue())


def review(path, binding, *, requests=None, resolutions=None):
    evidence = {
        "schema_version": 1,
        "binding": binding,
        "pause": {
            "release": "controlled-release",
            "image": "controlled-image",
            "operation": "controlled-pause",
            "creator_evidence": {
                creator: "controlled-worker-and-request-population"
                for creator in ["backend", "publisher", "coupon-maintenance", "recovery-cli"]
            },
        },
        "legacy": {
            "completeness_evidence": "controlled-complete-request-population",
            "no_applicable_dispatch_evidence": None
            if requests
            else "controlled-no-legacy-requests",
            "requests": requests or [],
        },
        "review": {
            "operator": "controlled-operator",
            "reviewer": "controlled-reviewer",
            "record": "controlled-review-record",
        },
        "dispatch_resolutions": resolutions or [],
    }
    content = json.dumps(evidence).encode()
    path.write_bytes(content)
    return [
        "--evidence",
        str(path),
        "--reviewed-evidence-sha256",
        hashlib.sha256(content).hexdigest(),
    ]
