"""Fail-closed audit boundary for synthetic rollback simulation.

This module does not execute a rollback or grant authority. It allows one mocked
rollback effect only after a trusted rollback capability has already been assessed
and an exact audit event is newly admitted. Terminal status requires a separately
trusted rollback result plus a second exact audit event.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from threading import Lock

from .audit import AuditBuffer, AuditEvent
from .contracts import token, utc
from .rollback import RollbackAssessment, RollbackCapabilityBinding, RollbackResultBinding

_PROFILE = "delegated_simulation"
_ROLLBACK_OUTCOMES = frozenset({"verified_rolled_back", "rollback_failed", "rollback_unknown"})


def _digest(value: str, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase sha256 digest")
    return value


def rollback_capability_digest(capability: RollbackCapabilityBinding) -> str:
    """Canonical fingerprint for one exact trusted capability binding."""
    if not isinstance(capability, RollbackCapabilityBinding):
        raise ValueError("trusted rollback capability required")
    payload = {
        "capability_id": capability.capability_id,
        "delivery_id": capability.delivery_id,
        "effect_digest": capability.effect_digest,
        "expires_at": utc(capability.expires_at).isoformat(),
        "issued_at": utc(capability.issued_at).isoformat(),
        "partition": capability.partition,
        "policy_revision": capability.policy_revision,
        "principal_ref": capability.principal_ref,
        "proposal_digest": capability.proposal_digest,
        "session_id": capability.session_id,
        "state_digest": capability.state_digest,
        "step_id": capability.step_id,
        "version": capability.version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def _audit_outcome(rollback_outcome: str) -> str:
    mapping = {
        "verified_rolled_back": "verified_complete",
        "rollback_failed": "failed",
        "rollback_unknown": "outcome_unknown",
    }
    try:
        return mapping[rollback_outcome]
    except KeyError as exc:
        raise ValueError("unsupported rollback outcome") from exc


@dataclass(frozen=True)
class RollbackSimulationReceipt:
    status: str
    reason: str
    request_id: str
    session_id: str
    step_id: str
    delivery_id: str
    capability_id: str
    capability_digest: str
    mocked_rollbacks: int
    rollback_available: bool
    result_ref: str | None = None
    result_digest: str | None = None
    authorized: bool = False
    execute: bool = False
    external_actions: int = 0
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1" or self.status not in {
            "denied", "attempted", "reconciliation_required",
            "verified_rolled_back", "rollback_failed", "rollback_unknown",
        }:
            raise ValueError("unsupported rollback simulation receipt")
        for value in (
            self.reason, self.request_id, self.session_id, self.step_id,
            self.delivery_id, self.capability_id,
        ):
            token(value)
        _digest(self.capability_digest, field="rollback capability")
        if isinstance(self.mocked_rollbacks, bool) or self.mocked_rollbacks not in {0, 1}:
            raise ValueError("rollback receipt may record at most one mocked rollback")
        if not isinstance(self.rollback_available, bool):
            raise ValueError("rollback availability must be boolean")
        if self.authorized is not False or self.execute is not False or self.external_actions != 0:
            raise ValueError("rollback simulation receipt cannot grant execution authority")
        has_result = self.result_ref is not None or self.result_digest is not None
        if has_result and (self.result_ref is None or self.result_digest is None):
            raise ValueError("partial rollback result receipt")
        if self.result_ref is not None:
            token(self.result_ref)
            _digest(self.result_digest, field="rollback result")
        if self.status in _ROLLBACK_OUTCOMES and self.result_ref is None:
            raise ValueError("rollback outcome receipt requires result provenance")
        if self.status != "denied" and self.rollback_available is not True:
            raise ValueError("rollback lifecycle receipt requires trusted capability provenance")
        if self.status == "denied" and (self.rollback_available is not False or self.mocked_rollbacks != 0):
            raise ValueError("denied rollback receipt must remain non-effecting")


class AuditedRollbackSimulation:
    """One-effect synthetic rollback with audit-before-effect and trusted reconciliation."""

    def __init__(
        self,
        capability: RollbackCapabilityBinding,
        *,
        assessment: RollbackAssessment,
        audit_sink: AuditBuffer | None,
    ) -> None:
        if not isinstance(capability, RollbackCapabilityBinding):
            raise ValueError("trusted rollback capability required")
        if not isinstance(assessment, RollbackAssessment):
            raise ValueError("trusted rollback assessment required")
        if (
            assessment.status != "available_for_simulation"
            or assessment.rollback_available is not True
            or assessment.capability_id != capability.capability_id
            or assessment.effect_digest != capability.effect_digest
            or assessment.session_id != capability.session_id
            or assessment.step_id != capability.step_id
            or assessment.delivery_id != capability.delivery_id
        ):
            raise ValueError("rollback assessment does not bind capability")
        self._capability = capability
        self._capability_digest = rollback_capability_digest(capability)
        self._audit_sink = audit_sink
        self._attempt: RollbackSimulationReceipt | None = None
        self._attempted_at: datetime | None = None
        self._results: dict[str, RollbackResultBinding] = {}
        self._terminal: RollbackSimulationReceipt | None = None
        self._lock = Lock()

    def _denied(self, request_id: str, reason: str) -> RollbackSimulationReceipt:
        return RollbackSimulationReceipt(
            "denied", reason, request_id, self._capability.session_id,
            self._capability.step_id, self._capability.delivery_id,
            self._capability.capability_id, self._capability_digest, 0, False,
        )

    def _receipt(
        self,
        request_id: str,
        status: str,
        reason: str,
        *,
        mocked_rollbacks: int = 0,
        result: RollbackResultBinding | None = None,
    ) -> RollbackSimulationReceipt:
        return RollbackSimulationReceipt(
            status, reason, request_id, self._capability.session_id,
            self._capability.step_id, self._capability.delivery_id,
            self._capability.capability_id, self._capability_digest,
            mocked_rollbacks, True,
            None if result is None else result.result_ref,
            None if result is None else result.result_digest,
        )

    def _attempt_audit_matches(self, event: AuditEvent, request_id: str, now: datetime) -> bool:
        cap = self._capability
        return (
            event.request_id == request_id
            and event.partition == cap.partition
            and event.principal_ref == cap.principal_ref
            and event.profile == _PROFILE
            and event.policy_revision == cap.policy_revision
            and event.proposal_id is None
            and event.grant_ref is None
            and event.bound_approval_refs == ()
            and event.evidence_refs == (cap.capability_id,)
            and event.evidence_digests == (self._capability_digest,)
            and event.decision == "attempted"
            and event.reason == "rollback_attempted"
            and event.outcome == "attempted"
            and utc(event.recorded_at) == now
        )

    def attempt(
        self,
        *,
        request_id: str,
        now: datetime,
        current_policy_revision: str,
        current_state_digest: str,
        current_profile: str,
        authority_available: bool,
        cancelled: bool,
        capability_revoked: bool,
        audit_event: AuditEvent,
    ) -> RollbackSimulationReceipt:
        token(request_id)
        now = utc(now)
        token(current_policy_revision)
        _digest(current_state_digest, field="current_state_digest")
        if current_profile not in {"read_only", "recommend", "approval_required", "delegated_simulation"}:
            raise ValueError("unsupported current profile")
        if not all(isinstance(value, bool) for value in (authority_available, cancelled, capability_revoked)):
            raise ValueError("boolean flags required")
        if not isinstance(audit_event, AuditEvent):
            raise ValueError("audit event required")
        with self._lock:
            if self._attempt is not None:
                if request_id == self._attempt.request_id:
                    return self._terminal or self._attempt
                return self._receipt(request_id, "reconciliation_required", "rollback_already_attempted")
            checks = (
                (not authority_available, "authority_unavailable"),
                (cancelled, "session_cancelled"),
                (capability_revoked, "rollback_capability_revoked"),
                (current_profile != _PROFILE, "rollback_profile_mismatch"),
                (current_policy_revision != self._capability.policy_revision, "rollback_policy_mismatch"),
                (current_state_digest != self._capability.state_digest, "rollback_state_mismatch"),
                (now < utc(self._capability.issued_at), "rollback_capability_not_yet_valid"),
                (now >= utc(self._capability.expires_at), "rollback_capability_expired"),
            )
            for blocked, reason in checks:
                if blocked:
                    return self._denied(request_id, reason)
            if not self._attempt_audit_matches(audit_event, request_id, now):
                return self._denied(request_id, "rollback_audit_binding_mismatch")
            if self._audit_sink is None:
                return self._denied(request_id, "rollback_audit_unavailable")
            try:
                admitted = self._audit_sink.append(audit_event)
            except (RuntimeError, ValueError):
                return self._denied(request_id, "rollback_audit_unavailable")
            if admitted is not True:
                return self._denied(request_id, "rollback_audit_replay_ambiguous")
            self._attempted_at = now
            self._attempt = self._receipt(
                request_id, "attempted", "rollback_mocked_effect_recorded", mocked_rollbacks=1
            )
            return self._attempt

    def _result_matches(self, result: RollbackResultBinding) -> bool:
        cap = self._capability
        return (
            result.capability_id == cap.capability_id
            and result.session_id == cap.session_id
            and result.step_id == cap.step_id
            and result.delivery_id == cap.delivery_id
            and result.result_ref != cap.capability_id
        )

    def _result_audit_matches(
        self, event: AuditEvent, request_id: str, result: RollbackResultBinding, now: datetime
    ) -> bool:
        cap = self._capability
        return (
            event.request_id == request_id
            and event.partition == cap.partition
            and event.principal_ref == cap.principal_ref
            and event.profile == _PROFILE
            and event.policy_revision == cap.policy_revision
            and event.proposal_id is None
            and event.grant_ref is None
            and event.bound_approval_refs == ()
            and event.evidence_refs == (cap.capability_id, result.result_ref)
            and event.evidence_digests == (self._capability_digest, result.result_digest)
            and event.decision == "returned"
            and event.reason == "rollback_reconciled"
            and event.outcome == _audit_outcome(result.outcome)
            and utc(event.recorded_at) == now
        )

    def reconcile(
        self,
        result: RollbackResultBinding,
        *,
        request_id: str,
        now: datetime,
        audit_event: AuditEvent,
    ) -> RollbackSimulationReceipt:
        if not isinstance(result, RollbackResultBinding):
            raise ValueError("trusted rollback result required")
        token(request_id)
        now = utc(now)
        if not isinstance(audit_event, AuditEvent):
            raise ValueError("audit event required")
        with self._lock:
            if self._attempt is None or self._attempted_at is None:
                return self._denied(request_id, "rollback_not_attempted")
            if request_id != self._attempt.request_id:
                return self._receipt(request_id, "reconciliation_required", "rollback_request_mismatch")
            existing = self._results.get(result.result_ref)
            if existing is not None:
                if existing != result:
                    return self._receipt(
                        request_id, "reconciliation_required", "rollback_result_identity_collision"
                    )
                return self._terminal or self._attempt
            if self._terminal is not None and self._terminal.status in {"verified_rolled_back", "rollback_failed"}:
                return self._terminal
            if not self._result_matches(result):
                return self._receipt(
                    request_id, "reconciliation_required", "rollback_result_binding_mismatch"
                )
            observed = utc(result.observed_at)
            if observed < self._attempted_at or observed > now:
                return self._receipt(
                    request_id, "reconciliation_required", "rollback_result_time_mismatch"
                )
            if not self._result_audit_matches(audit_event, request_id, result, now):
                return self._receipt(
                    request_id, "reconciliation_required", "rollback_audit_binding_mismatch"
                )
            if self._audit_sink is None:
                return self._receipt(request_id, "reconciliation_required", "rollback_audit_unavailable")
            try:
                admitted = self._audit_sink.append(audit_event)
            except (RuntimeError, ValueError):
                return self._receipt(request_id, "reconciliation_required", "rollback_audit_unavailable")
            if admitted is not True:
                return self._receipt(
                    request_id, "reconciliation_required", "rollback_audit_replay_ambiguous"
                )
            self._results[result.result_ref] = result
            self._terminal = self._receipt(
                request_id, result.outcome, "rollback_reconciled", result=result
            )
            return self._terminal
