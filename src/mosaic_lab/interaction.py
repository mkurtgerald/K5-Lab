"""Typed, non-executing interaction proposal boundary.

All proposal fields are untrusted input. Authenticated identity, permissions,
policy revision, and approvals are supplied separately by trusted server-side
context. This module has no transport or executor.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from math import isfinite
from typing import Mapping

from .contracts import token, utc, unit_score

_MAX_PARAMETERS = 16
_MAX_EVIDENCE = 32
_MAX_VALUE_CHARS = 128
_ALLOWED_PROFILES = frozenset({"read_only", "recommend", "approval_required", "delegated_simulation"})
_PROPOSAL_FIELDS = frozenset(
    {
        "version",
        "partition",
        "request_id",
        "proposal_id",
        "action_ref",
        "target_ref",
        "parameters",
        "evidence_refs",
        "issued_at",
        "expires_at",
        "untrusted_score",
        "untrusted_rationale",
    }
)


def _bounded_text(value: object, *, field: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    if (not allow_empty and not value) or len(value) > _MAX_VALUE_CHARS:
        raise ValueError(f"{field} is outside the bounded text limit")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"{field} contains control characters")
    return value


def _timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO timestamp") from exc
    return utc(parsed)


@dataclass(frozen=True)
class EvidenceRef:
    partition: str
    record_id: str
    observed_at: datetime

    def __post_init__(self) -> None:
        token(self.partition)
        token(self.record_id)
        utc(self.observed_at)


@dataclass(frozen=True)
class ProposalEnvelope:
    partition: str
    request_id: str
    proposal_id: str
    action_ref: str
    target_ref: str
    parameters: tuple[tuple[str, str], ...]
    evidence_refs: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    untrusted_score: float = 0.0
    untrusted_rationale: str = ""
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1":
            raise ValueError("unsupported proposal version")
        for value in (
            self.partition,
            self.request_id,
            self.proposal_id,
            self.action_ref,
            self.target_ref,
        ):
            token(value)
        issued_at = utc(self.issued_at)
        expires_at = utc(self.expires_at)
        if expires_at <= issued_at:
            raise ValueError("proposal expiry must follow issue time")
        if not isinstance(self.parameters, tuple) or len(self.parameters) > _MAX_PARAMETERS:
            raise ValueError("parameters must be a bounded immutable tuple")
        keys: list[str] = []
        for item in self.parameters:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ValueError("parameter entries must be key/value tuples")
            key, value = item
            token(key)
            _bounded_text(value, field="parameter value", allow_empty=True)
            keys.append(key)
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate parameter key")
        if not isinstance(self.evidence_refs, tuple) or not self.evidence_refs:
            raise ValueError("proposal requires evidence")
        if len(self.evidence_refs) > _MAX_EVIDENCE:
            raise ValueError("too many evidence references")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("duplicate evidence reference")
        for record_id in self.evidence_refs:
            token(record_id)
        unit_score(self.untrusted_score)
        _bounded_text(
            self.untrusted_rationale,
            field="untrusted rationale",
            allow_empty=True,
        )


@dataclass(frozen=True)
class TrustedAuthority:
    partition: str
    principal_ref: str
    profile: str
    allowed_actions: tuple[str, ...]
    allowed_targets: tuple[str, ...]
    policy_revision: str
    valid_until: datetime
    authenticated: bool = True
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1":
            raise ValueError("unsupported authority version")
        for value in (self.partition, self.principal_ref, self.policy_revision):
            token(value)
        if self.profile not in _ALLOWED_PROFILES:
            raise ValueError("unsupported authority profile")
        if not isinstance(self.authenticated, bool):
            raise ValueError("authenticated must be boolean")
        utc(self.valid_until)
        for values, field in (
            (self.allowed_actions, "allowed_actions"),
            (self.allowed_targets, "allowed_targets"),
        ):
            if not isinstance(values, tuple) or len(values) > 64:
                raise ValueError(f"{field} must be a bounded immutable tuple")
            if len(set(values)) != len(values):
                raise ValueError(f"{field} contains duplicates")
            for value in values:
                token(value)


@dataclass(frozen=True)
class ProposalDecision:
    status: str
    reason: str
    proposal_id: str
    effect_digest: str
    authorized: bool = False
    execute: bool = False
    external_actions: int = 0
    version: str = "1"

    def __post_init__(self) -> None:
        if self.status not in {"denied", "abstain", "recommendation", "awaiting_approval"}:
            raise ValueError("unsupported decision status")
        token(self.reason)
        token(self.proposal_id)
        if (
            not isinstance(self.effect_digest, str)
            or len(self.effect_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.effect_digest)
        ):
            raise ValueError("invalid effect digest")
        if self.version != "1":
            raise ValueError("unsupported decision version")
        if self.authorized is not False or self.execute is not False or self.external_actions != 0:
            raise ValueError("public interaction decisions cannot grant execution authority")


def parse_untrusted_proposal(payload: Mapping[str, object]) -> ProposalEnvelope:
    if not isinstance(payload, Mapping):
        raise ValueError("proposal payload must be a mapping")
    unknown = set(payload) - _PROPOSAL_FIELDS
    missing = {
        "partition",
        "request_id",
        "proposal_id",
        "action_ref",
        "target_ref",
        "parameters",
        "evidence_refs",
        "issued_at",
        "expires_at",
    } - set(payload)
    if unknown:
        raise ValueError("untrusted proposal contains unsupported fields")
    if missing:
        raise ValueError("untrusted proposal is missing required fields")
    version = payload.get("version", "1")
    if version != "1":
        raise ValueError("unsupported proposal version")

    raw_parameters = payload["parameters"]
    if not isinstance(raw_parameters, Mapping):
        raise ValueError("parameters must be an object")
    if len(raw_parameters) > _MAX_PARAMETERS:
        raise ValueError("too many parameters")
    parameters: list[tuple[str, str]] = []
    for key, value in raw_parameters.items():
        if not isinstance(key, str):
            raise ValueError("parameter key must be text")
        parameters.append((key, _bounded_text(value, field="parameter value", allow_empty=True)))
    parameters.sort(key=lambda item: item[0])

    raw_evidence = payload["evidence_refs"]
    if not isinstance(raw_evidence, (list, tuple)):
        raise ValueError("evidence_refs must be a list")
    evidence_refs = tuple(raw_evidence)
    if any(not isinstance(item, str) for item in evidence_refs):
        raise ValueError("evidence_refs must contain text tokens")

    score = payload.get("untrusted_score", 0.0)
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not isfinite(score):
        raise ValueError("untrusted_score must be finite numeric")

    return ProposalEnvelope(
        partition=payload["partition"],  # type: ignore[arg-type]
        request_id=payload["request_id"],  # type: ignore[arg-type]
        proposal_id=payload["proposal_id"],  # type: ignore[arg-type]
        action_ref=payload["action_ref"],  # type: ignore[arg-type]
        target_ref=payload["target_ref"],  # type: ignore[arg-type]
        parameters=tuple(parameters),
        evidence_refs=evidence_refs,
        issued_at=_timestamp(payload["issued_at"], field="issued_at"),
        expires_at=_timestamp(payload["expires_at"], field="expires_at"),
        untrusted_score=unit_score(score),
        untrusted_rationale=_bounded_text(
            payload.get("untrusted_rationale", ""),
            field="untrusted rationale",
            allow_empty=True,
        ),
        version=version,
    )


def effect_digest(proposal: ProposalEnvelope) -> str:
    """Digest only authority-relevant proposal fields.

    Model rationale and model score are intentionally excluded: neither can
    enlarge authority or change the effect that a future approval would bind.
    """
    payload = {
        "version": proposal.version,
        "partition": proposal.partition,
        "request_id": proposal.request_id,
        "proposal_id": proposal.proposal_id,
        "action_ref": proposal.action_ref,
        "target_ref": proposal.target_ref,
        "parameters": list(proposal.parameters),
        "evidence_refs": list(proposal.evidence_refs),
        "issued_at": utc(proposal.issued_at).isoformat(),
        "expires_at": utc(proposal.expires_at).isoformat(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def evaluate_proposal(
    proposal: ProposalEnvelope,
    authority: TrustedAuthority,
    *,
    evidence: Mapping[str, EvidenceRef],
    current_policy_revision: str,
    now: datetime,
    max_evidence_age_seconds: float = 60.0,
) -> ProposalDecision:
    now = utc(now)
    digest = effect_digest(proposal)

    def decision(status: str, reason: str) -> ProposalDecision:
        return ProposalDecision(status=status, reason=reason, proposal_id=proposal.proposal_id, effect_digest=digest)

    if not authority.authenticated:
        return decision("denied", "unauthenticated")
    if proposal.partition != authority.partition:
        return decision("denied", "partition_mismatch")
    token(current_policy_revision)
    if current_policy_revision != authority.policy_revision:
        return decision("denied", "policy_changed")
    if now >= utc(authority.valid_until):
        return decision("denied", "authority_expired")
    if now < utc(proposal.issued_at):
        return decision("abstain", "future_proposal")
    if now >= utc(proposal.expires_at):
        return decision("denied", "proposal_expired")
    if proposal.action_ref not in authority.allowed_actions:
        return decision("denied", "action_out_of_scope")
    if proposal.target_ref not in authority.allowed_targets:
        return decision("denied", "target_out_of_scope")

    if (
        isinstance(max_evidence_age_seconds, bool)
        or not isinstance(max_evidence_age_seconds, (int, float))
        or not isfinite(max_evidence_age_seconds)
        or max_evidence_age_seconds <= 0
    ):
        raise ValueError("invalid evidence freshness limit")

    for record_id in proposal.evidence_refs:
        item = evidence.get(record_id)
        if item is None:
            return decision("abstain", "missing_evidence")
        if item.partition != authority.partition:
            return decision("denied", "cross_partition_evidence")
        age = (now - utc(item.observed_at)).total_seconds()
        if age < 0:
            return decision("abstain", "future_evidence")
        if age > float(max_evidence_age_seconds):
            return decision("abstain", "stale_evidence")

    if authority.profile == "read_only":
        return decision("denied", "profile_read_only")
    if authority.profile == "approval_required":
        return decision("awaiting_approval", "approval_required")
    if authority.profile == "delegated_simulation":
        return decision("recommendation", "simulation_only")
    return decision("recommendation", "non_executing_only")
