"""Exact evidence-content binding for non-authorizing proposal evaluation.

This module is a narrow precursor for approval/replay hardening. It binds one
proposal digest to the exact trusted evidence content digests and observation
times used to evaluate it. It does not grant approval or execution authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Mapping

from .contracts import token, utc
from .interaction import ProposalEnvelope, effect_digest

_MAX_EVIDENCE = 32


def _sha256_digest(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{field} must be a lowercase sha256 digest")
    return value


@dataclass(frozen=True)
class EvidenceContentBinding:
    """Trusted identity + exact content fingerprint for one evidence record."""

    partition: str
    record_id: str
    content_digest: str
    observed_at: datetime
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1":
            raise ValueError("unsupported evidence-content binding version")
        token(self.partition)
        token(self.record_id)
        _sha256_digest(self.content_digest, field="content_digest")
        utc(self.observed_at)


@dataclass(frozen=True)
class BoundProposalEvidence:
    """Canonical non-authorizing digest binding a proposal to exact evidence."""

    proposal_id: str
    base_proposal_digest: str
    bound_digest: str
    evidence_refs: tuple[str, ...]
    evidence_digests: tuple[str, ...]
    authorized: bool = False
    execute: bool = False
    external_actions: int = 0
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1":
            raise ValueError("unsupported bound-proposal version")
        token(self.proposal_id)
        _sha256_digest(self.base_proposal_digest, field="base_proposal_digest")
        _sha256_digest(self.bound_digest, field="bound_digest")
        if (
            not isinstance(self.evidence_refs, tuple)
            or not isinstance(self.evidence_digests, tuple)
            or not self.evidence_refs
            or len(self.evidence_refs) > _MAX_EVIDENCE
            or len(self.evidence_refs) != len(self.evidence_digests)
        ):
            raise ValueError("evidence binding must be bounded and complete")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("duplicate evidence reference")
        for record_id in self.evidence_refs:
            token(record_id)
        for digest in self.evidence_digests:
            _sha256_digest(digest, field="evidence digest")
        if self.authorized is not False or self.execute is not False or self.external_actions != 0:
            raise ValueError("evidence binding cannot grant execution authority")


def bind_proposal_evidence(
    proposal: ProposalEnvelope,
    evidence: Mapping[str, EvidenceContentBinding],
) -> BoundProposalEvidence:
    """Bind one proposal to the exact trusted evidence state used for evaluation.

    The returned digest is suitable as a precursor for later approval binding.
    It is deliberately non-authorizing and is not wired to an executor.
    """

    if type(proposal) is not ProposalEnvelope:
        raise ValueError("trusted proposal envelope required")
    if not isinstance(evidence, Mapping):
        raise ValueError("evidence bindings must be a mapping")

    try:
        keys = tuple(evidence.keys())
    except Exception as exc:
        raise ValueError("evidence binding keys unavailable") from exc
    if len(keys) > _MAX_EVIDENCE:
        raise ValueError("too many evidence bindings")
    if set(keys) != set(proposal.evidence_refs):
        raise ValueError("evidence bindings must exactly match proposal references")

    entries: list[tuple[str, str, str, str]] = []
    digests: list[str] = []
    for record_id in proposal.evidence_refs:
        try:
            item = evidence.get(record_id)
        except Exception as exc:
            raise ValueError("evidence binding unavailable") from exc
        if type(item) is not EvidenceContentBinding:
            raise ValueError("trusted evidence-content binding required")
        if item.record_id != record_id:
            raise ValueError("evidence identity mismatch")
        if item.partition != proposal.partition:
            raise ValueError("cross-partition evidence binding")
        observed_at = utc(item.observed_at).isoformat()
        entries.append((item.partition, item.record_id, item.content_digest, observed_at))
        digests.append(item.content_digest)

    base_digest = effect_digest(proposal)
    payload = {
        "version": "1",
        "proposal_id": proposal.proposal_id,
        "partition": proposal.partition,
        "base_proposal_digest": base_digest,
        "evidence": entries,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    bound_digest = sha256(encoded).hexdigest()
    return BoundProposalEvidence(
        proposal_id=proposal.proposal_id,
        base_proposal_digest=base_digest,
        bound_digest=bound_digest,
        evidence_refs=tuple(proposal.evidence_refs),
        evidence_digests=tuple(digests),
    )
