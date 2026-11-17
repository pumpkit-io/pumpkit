"""Protected operator evidence, whose historical completeness needs human review."""

import hashlib
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class Binding(EvidenceModel):
    instance_id: str
    generation: int
    config_fingerprint: str
    account_id: str
    livemode: bool


class Pause(EvidenceModel):
    release: str = Field(min_length=1)
    image: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    creator_evidence: dict[str, str]


class LegacyRequest(EvidenceModel):
    request_reference: str = Field(min_length=1)
    creator: Literal["backend", "publisher", "coupon-maintenance", "recovery-cli"]
    parameters_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    relationship_evidence: str = Field(min_length=1)
    outcome_evidence: str = Field(min_length=1)
    outcome: Literal["object", "execution_not_started", "provider_resolved_no_object", "unknown"]
    session_id: Optional[str] = None
    paid_signup_id: Optional[str] = None
    accepted_offer_sha256: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    idempotency_key_sha256: Optional[str] = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    parameters: Optional[dict[str, Any]] = None


class Legacy(EvidenceModel):
    completeness_evidence: str = Field(min_length=1)
    no_applicable_dispatch_evidence: Optional[str] = None
    requests: list[LegacyRequest]


class Review(EvidenceModel):
    operator: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    record: str = Field(min_length=1)


class DispatchResolution(EvidenceModel):
    dispatch_id: str = Field(min_length=1)
    parameters_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    worker_resolution_evidence: str = Field(min_length=1)
    provider_resolution_evidence: str = Field(min_length=1)
    outcome: Literal["object", "provider_resolved_no_object"]
    session_id: Optional[str] = None


class Evidence(EvidenceModel):
    schema_version: Literal[1]
    binding: Binding
    pause: Pause
    legacy: Legacy
    review: Review
    dispatch_resolutions: list[DispatchResolution] = Field(default_factory=list)


def load(
    path: Optional[str], reviewed_digest: Optional[str], binding: dict
) -> tuple[Optional[Evidence], str]:
    if not path or not reviewed_digest:
        return None, "legacy_evidence_required"
    try:
        content = Path(path).read_bytes()
        if hashlib.sha256(content).hexdigest() != reviewed_digest:
            return None, "evidence_digest_mismatch"
        evidence = Evidence.model_validate_json(content)
    except (OSError, ValidationError, ValueError):
        return None, "evidence_invalid"
    if evidence.binding.model_dump() != binding:
        return None, "evidence_binding_mismatch"
    if set(evidence.pause.creator_evidence) != {
        "backend",
        "publisher",
        "coupon-maintenance",
        "recovery-cli",
    } or not all(evidence.pause.creator_evidence.values()):
        return None, "creator_evidence_incomplete"
    if evidence.review.operator == evidence.review.reviewer:
        return None, "independent_review_required"
    if not evidence.legacy.requests and not evidence.legacy.no_applicable_dispatch_evidence:
        return None, "legacy_completeness_unverified"
    for request in evidence.legacy.requests:
        linked = [
            request.paid_signup_id,
            request.accepted_offer_sha256,
            request.idempotency_key_sha256,
            request.parameters,
        ]
        if any(value is not None for value in linked) and (
            not all(value is not None for value in linked)
            or request.outcome not in {"execution_not_started", "provider_resolved_no_object"}
        ):
            return None, "legacy_operation_evidence_incomplete"
        if request.outcome == "unknown" or (request.outcome == "object") != bool(
            request.session_id
        ):
            return None, "legacy_request_unresolved"
    if len({r.dispatch_id for r in evidence.dispatch_resolutions}) != len(
        evidence.dispatch_resolutions
    ):
        return None, "dispatch_resolution_duplicate"
    for resolution in evidence.dispatch_resolutions:
        if (resolution.outcome == "object") != bool(resolution.session_id):
            return None, "dispatch_resolution_invalid"
    return evidence, ""
